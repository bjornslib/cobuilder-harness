package iterm2

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// IsInsideTmux returns true when the process is running inside a tmux session.
func IsInsideTmux() bool {
	return os.Getenv("TMUX") != ""
}

// IsITerm2 returns true when the terminal emulator is iTerm2.
func IsITerm2() bool {
	return os.Getenv("TERM_PROGRAM") == "iTerm.app"
}

// AttachStrategy describes how to attach to a session.
type AttachStrategy int

const (
	// SameWindowCC attaches in-place via tmux CC mode (iTerm2 + inside tmux).
	SameWindowCC AttachStrategy = iota
	// SwitchClient switches the tmux client (inside tmux, not iTerm2).
	SwitchClient
	// NewTabCC opens a new iTerm2 tab then attaches via CC mode.
	NewTabCC
	// PlainAttach falls back to a regular tmux attach in the same terminal.
	PlainAttach
)

// DetectStrategy picks the best attachment strategy for the current environment.
func DetectStrategy() AttachStrategy {
	insideTmux := IsInsideTmux()
	isITerm := IsITerm2()

	switch {
	case insideTmux && isITerm:
		return SameWindowCC
	case insideTmux && !isITerm:
		return SwitchClient
	case !insideTmux && isITerm:
		return NewTabCC
	default:
		return PlainAttach
	}
}

// Attach attaches to `session` using the appropriate strategy.
// For strategies that exec-replace the process (SameWindowCC, PlainAttach,
// SwitchClient) this function does not return on success.
func Attach(session string, strategy AttachStrategy) error {
	switch strategy {
	case SameWindowCC:
		return execReplace("tmux", "-CC", "attach", "-t", session)

	case SwitchClient:
		return exec.Command("tmux", "switch-client", "-t", session).Run()

	case NewTabCC:
		return openNewITerm2Tab(session)

	case PlainAttach:
		return execReplace("tmux", "attach", "-t", session)
	}
	return fmt.Errorf("unknown strategy %d", strategy)
}

// StrategyLabel returns a human-readable description of the strategy.
func StrategyLabel(s AttachStrategy) string {
	switch s {
	case SameWindowCC:
		return "attach (iTerm2 CC, same window)"
	case SwitchClient:
		return "switch-client (inside tmux)"
	case NewTabCC:
		return "open new iTerm2 tab"
	case PlainAttach:
		return "attach (plain tmux)"
	}
	return "attach"
}

// openNewITerm2Tab uses AppleScript to open a new iTerm2 tab and attach.
func openNewITerm2Tab(session string) error {
	// Escape single quotes in session name for shell safety.
	safe := strings.ReplaceAll(session, "'", `'"'"'`)
	script := fmt.Sprintf(`
tell application "iTerm2"
  tell current window
    create tab with default profile
    tell current session
      write text "tmux -CC attach -t '%s'"
    end tell
  end tell
end tell
`, safe)
	cmd := exec.Command("osascript", "-e", script)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("osascript: %w\n%s", err, out)
	}
	return nil
}

// execReplace replaces the current process with the given command (Unix exec).
// On non-Unix systems this falls through to a regular Run().
func execReplace(name string, args ...string) error {
	path, err := exec.LookPath(name)
	if err != nil {
		return err
	}
	// syscall.Exec replaces the process image; use os/exec.Cmd on unsupported OSes.
	return syscallExec(path, append([]string{name}, args...), os.Environ())
}
