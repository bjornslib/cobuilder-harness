//go:build windows

package iterm2

import "os/exec"

func syscallExec(path string, argv []string, env []string) error {
	cmd := exec.Command(path, argv[1:]...)
	cmd.Env = env
	return cmd.Run()
}
