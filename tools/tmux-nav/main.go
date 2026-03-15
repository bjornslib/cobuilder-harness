package main

import (
	"fmt"
	"os"

	"github.com/bjornslib/tmux-nav/iterm2"
	"github.com/bjornslib/tmux-nav/tmux"
	"github.com/bjornslib/tmux-nav/tui"
	tea "github.com/charmbracelet/bubbletea"
)

const usage = `tmux-nav — interactive tmux session navigator

Usage:
  tmux-nav           Launch interactive TUI
  tmux-nav list      List sessions (plain text)
  tmux-nav peek <s>  Peek at session <s>
  tmux-nav attach <s> Attach to session <s>
  tmux-nav kill <s>  Kill session <s>
  tmux-nav -h        Show this help
`

func main() {
	if len(os.Args) < 2 {
		runTUI()
		return
	}

	switch os.Args[1] {
	case "-h", "--help", "help":
		fmt.Print(usage)

	case "list":
		sessions, err := tmux.ListSessions()
		if err != nil {
			die("list:", err)
		}
		if len(sessions) == 0 {
			fmt.Println("(no sessions)")
			return
		}
		for _, s := range sessions {
			status := "det"
			if s.Attached {
				status = "att"
			}
			fmt.Printf("%-40s  %dw  %s\n", s.Name, s.Windows, status)
		}

	case "peek":
		if len(os.Args) < 3 {
			die("peek requires a session name", nil)
		}
		out, err := tmux.CapturePanes(os.Args[2], 40)
		if err != nil {
			die("peek:", err)
		}
		fmt.Print(out)

	case "attach":
		if len(os.Args) < 3 {
			die("attach requires a session name", nil)
		}
		strategy := iterm2.DetectStrategy()
		if err := iterm2.Attach(os.Args[2], strategy); err != nil {
			die("attach:", err)
		}

	case "kill":
		if len(os.Args) < 3 {
			die("kill requires a session name", nil)
		}
		if err := tmux.KillSession(os.Args[2]); err != nil {
			die("kill:", err)
		}
		fmt.Println("killed", os.Args[2])

	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n\n%s", os.Args[1], usage)
		os.Exit(1)
	}
}

func runTUI() {
	m := tui.New()
	p := tea.NewProgram(m, tea.WithAltScreen())
	finalModel, err := p.Run()
	if err != nil {
		die("tui:", err)
	}

	// After TUI exits, handle attachment if the user selected a session.
	if fm, ok := finalModel.(tui.Model); ok && fm.AttachSession != "" {
		if err := iterm2.Attach(fm.AttachSession, fm.Strategy); err != nil {
			die("attach:", err)
		}
	}
}

func die(msg string, err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s %v\n", msg, err)
	} else {
		fmt.Fprintln(os.Stderr, msg)
	}
	os.Exit(1)
}
