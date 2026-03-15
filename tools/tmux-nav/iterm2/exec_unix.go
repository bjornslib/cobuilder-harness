//go:build !windows

package iterm2

import "syscall"

func syscallExec(path string, argv []string, env []string) error {
	return syscall.Exec(path, argv, env)
}
