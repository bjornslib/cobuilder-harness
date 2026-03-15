package tui

import (
	"fmt"
	"strings"
	"time"

	"github.com/bjornslib/tmux-nav/iterm2"
	"github.com/bjornslib/tmux-nav/tmux"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ── Styles ─────────────────────────────────────────────────────────────────

var (
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("86")).
			Padding(0, 1)

	selectedStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("212")).
			Bold(true)

	normalStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("252"))

	attachedBadge = lipgloss.NewStyle().
			Foreground(lipgloss.Color("46")).
			SetString("●")

	detachedBadge = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			SetString("○")

	previewBorderStyle = lipgloss.NewStyle().
				Border(lipgloss.RoundedBorder()).
				BorderForeground(lipgloss.Color("62")).
				Padding(0, 1)

	listBorderStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("62")).
			Padding(0, 1)

	helpStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("241"))

	errorStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("196"))

	confirmStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("214")).
			Bold(true)
)

// ── Messages ───────────────────────────────────────────────────────────────

type sessionsLoadedMsg struct{ sessions []tmux.Session }
type previewLoadedMsg struct{ content string }
type errMsg struct{ err error }
type tickMsg time.Time

// ── Model ──────────────────────────────────────────────────────────────────

type uiMode int

const (
	modeList uiMode = iota
	modeConfirmKill
)

// Model is the Bubble Tea model.
// After p.Run() returns, inspect AttachSession: if non-empty, caller should attach.
type Model struct {
	sessions      []tmux.Session
	cursor        int
	preview       string
	err           error
	mode          uiMode
	width         int
	height        int
	Strategy      iterm2.AttachStrategy
	statusMsg     string
	AttachSession string // set when user picks a session to attach to
}

// New creates an initialised Model.
func New() Model {
	return Model{
		Strategy: iterm2.DetectStrategy(),
	}
}

// Init kicks off the initial session load.
func (m Model) Init() tea.Cmd {
	return tea.Batch(loadSessions, tickCmd())
}

// ── Update ─────────────────────────────────────────────────────────────────

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case sessionsLoadedMsg:
		m.sessions = msg.sessions
		m.err = nil
		if m.cursor >= len(m.sessions) {
			m.cursor = safeMax(0, len(m.sessions)-1)
		}
		return m, m.loadPreview()

	case previewLoadedMsg:
		m.preview = msg.content
		return m, nil

	case errMsg:
		m.err = msg.err
		return m, nil

	case tickMsg:
		return m, tea.Batch(loadSessions, tickCmd())

	case tea.KeyMsg:
		return m.handleKey(msg)
	}

	return m, nil
}

func (m Model) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.mode == modeConfirmKill {
		switch msg.String() {
		case "y", "Y":
			if len(m.sessions) > 0 {
				session := m.sessions[m.cursor].Name
				if err := tmux.KillSession(session); err != nil {
					m.err = err
				} else {
					m.statusMsg = fmt.Sprintf("killed %q", session)
				}
			}
			m.mode = modeList
			return m, loadSessions
		default:
			m.mode = modeList
			m.statusMsg = "kill cancelled"
			return m, nil
		}
	}

	// modeList key handling
	switch msg.String() {
	case "q", "ctrl+c", "esc":
		return m, tea.Quit

	case "up", "k":
		if m.cursor > 0 {
			m.cursor--
			return m, m.loadPreview()
		}

	case "down", "j":
		if m.cursor < len(m.sessions)-1 {
			m.cursor++
			return m, m.loadPreview()
		}

	case "enter", "a":
		// Record the chosen session; main.go will attach after TUI exits.
		if len(m.sessions) > 0 {
			m.AttachSession = m.sessions[m.cursor].Name
			return m, tea.Quit
		}

	case "p":
		return m, m.loadPreview()

	case "d", "x":
		// d/x = kill session
		if len(m.sessions) > 0 {
			m.mode = modeConfirmKill
			m.statusMsg = ""
		}

	case "r":
		m.statusMsg = "refreshing…"
		return m, loadSessions
	}

	return m, nil
}

// ── View ───────────────────────────────────────────────────────────────────

func (m Model) View() string {
	if m.width == 0 {
		return "Loading…\n"
	}

	// Split horizontally: list | preview
	listW := m.width/2 - 2
	previewW := m.width - listW - 4

	listContent := m.renderList(listW)
	previewContent := m.renderPreview(previewW)

	left := listBorderStyle.Width(listW).Render(listContent)
	right := previewBorderStyle.Width(previewW).Render(previewContent)

	body := lipgloss.JoinHorizontal(lipgloss.Top, left, " ", right)

	header := titleStyle.Render(fmt.Sprintf("tmux-nav  %d session(s)  [%s]",
		len(m.sessions), iterm2.StrategyLabel(m.Strategy)))

	footer := m.renderFooter()

	return lipgloss.JoinVertical(lipgloss.Left, header, body, footer)
}

func (m Model) renderList(w int) string {
	if len(m.sessions) == 0 {
		return normalStyle.Render("(no sessions)")
	}

	var sb strings.Builder
	for i, s := range m.sessions {
		badge := detachedBadge.String()
		if s.Attached {
			badge = attachedBadge.String()
		}
		age := formatAge(s.LastUsed)
		label := fmt.Sprintf("%s %-28s  %dw  %s", badge, s.Name, s.Windows, age)

		if i == m.cursor {
			sb.WriteString(selectedStyle.Render("▶ "+label) + "\n")
		} else {
			sb.WriteString(normalStyle.Render("  "+label) + "\n")
		}
	}
	return sb.String()
}

func (m Model) renderPreview(w int) string {
	title := "(no session selected)"
	if len(m.sessions) > 0 {
		title = "Preview: " + m.sessions[m.cursor].Name
	}

	var content string
	if m.err != nil {
		content = errorStyle.Render("Error: " + m.err.Error())
	} else if m.preview == "" {
		content = normalStyle.Render("(empty pane)")
	} else {
		lines := strings.Split(m.preview, "\n")
		maxLines := m.height - 8
		if len(lines) > maxLines {
			lines = lines[len(lines)-maxLines:]
		}
		content = strings.Join(lines, "\n")
	}

	return lipgloss.JoinVertical(lipgloss.Left,
		titleStyle.Render(title),
		content,
	)
}

func (m Model) renderFooter() string {
	keys := "[↑↓/jk] navigate  [enter/a] attach  [p] preview  [d/x] kill  [r] reload  [q] quit"
	if m.mode == modeConfirmKill && len(m.sessions) > 0 {
		return confirmStyle.Render(fmt.Sprintf("Kill %q? [y/N]", m.sessions[m.cursor].Name))
	}
	help := helpStyle.Render(keys)
	if m.statusMsg != "" {
		return lipgloss.JoinVertical(lipgloss.Left, help, normalStyle.Render("  "+m.statusMsg))
	}
	return help
}

// ── Commands ───────────────────────────────────────────────────────────────

func loadSessions() tea.Msg {
	sessions, err := tmux.ListSessions()
	if err != nil {
		return errMsg{err}
	}
	return sessionsLoadedMsg{sessions}
}

func (m Model) loadPreview() tea.Cmd {
	if len(m.sessions) == 0 {
		return nil
	}
	session := m.sessions[m.cursor].Name
	return func() tea.Msg {
		content, err := tmux.CapturePanes(session, 40)
		if err != nil {
			return previewLoadedMsg{"(capture failed: " + err.Error() + ")"}
		}
		return previewLoadedMsg{content}
	}
}

func tickCmd() tea.Cmd {
	return tea.Tick(5*time.Second, func(t time.Time) tea.Msg {
		return tickMsg(t)
	})
}

// ── Helpers ────────────────────────────────────────────────────────────────

func formatAge(t time.Time) string {
	d := time.Since(t)
	switch {
	case d < time.Minute:
		return fmt.Sprintf("%ds", int(d.Seconds()))
	case d < time.Hour:
		return fmt.Sprintf("%dm", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh", int(d.Hours()))
	default:
		return fmt.Sprintf("%dd", int(d.Hours()/24))
	}
}

func safeMax(a, b int) int {
	if a > b {
		return a
	}
	return b
}
