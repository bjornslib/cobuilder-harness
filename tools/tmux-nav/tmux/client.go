package tmux

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// Session represents a tmux session with its metadata.
type Session struct {
	Name      string
	Windows   int
	Attached  bool
	LastUsed  time.Time
	ActivePane string // "window.pane" of the active pane
}

// ListSessions returns all active tmux sessions.
func ListSessions() ([]Session, error) {
	// Format: name|windows|attached|last_used
	format := "#{session_name}|#{session_windows}|#{session_attached}|#{session_activity}"
	out, err := exec.Command("tmux", "list-sessions", "-F", format).Output()
	if err != nil {
		// tmux exits non-zero when no sessions exist
		if len(out) == 0 {
			return nil, nil
		}
		return nil, fmt.Errorf("tmux list-sessions: %w", err)
	}

	var sessions []Session
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "|", 4)
		if len(parts) < 4 {
			continue
		}
		windows, _ := strconv.Atoi(parts[1])
		attached := parts[2] == "1"
		activitySec, _ := strconv.ParseInt(parts[3], 10, 64)
		lastUsed := time.Unix(activitySec, 0)

		sessions = append(sessions, Session{
			Name:     parts[0],
			Windows:  windows,
			Attached: attached,
			LastUsed: lastUsed,
		})
	}
	return sessions, nil
}

// CapturePanes returns the last `lines` lines of the active pane in `session`.
// It tries the active window/pane first, falling back to window 0 pane 0.
func CapturePanes(session string, lines int) (string, error) {
	target := fmt.Sprintf("%s:", session) // active window of session
	args := []string{
		"capture-pane",
		"-t", target,
		"-p",                          // print to stdout
		"-e",                          // preserve escape sequences
		"-S", fmt.Sprintf("-%d", lines), // start N lines back
	}
	out, err := exec.Command("tmux", args...).Output()
	if err != nil {
		// Fall back to explicit 0.0
		target = fmt.Sprintf("%s:0.0", session)
		args[3] = target
		out, err = exec.Command("tmux", args...).Output()
		if err != nil {
			return "", fmt.Errorf("capture-pane: %w", err)
		}
	}
	return string(out), nil
}

// KillSession kills the named session.
func KillSession(session string) error {
	return exec.Command("tmux", "kill-session", "-t", session).Run()
}

// SwitchClient switches the current tmux client to `session`.
// Used when already inside tmux (non-iTerm2).
func SwitchClient(session string) error {
	return exec.Command("tmux", "switch-client", "-t", session).Run()
}
