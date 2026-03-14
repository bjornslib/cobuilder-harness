"""CloseHandler — handles octagon (programmatic epic closure) nodes.

The close handler automates epic completion:
1. Pushes the worktree branch to remote
2. Creates a PR via GitHub CLI
3. Reports completion via signal file
4. Does NOT cleanup worktree — that requires wait.human approval

AC-E4-Close:
- Pushes branch to remote using git push
- Creates PR via GitHub CLI (gh pr create)
- Reports completion via signal file
- Returns SUCCESS when PR is created
- Returns FAILURE when git push or PR creation fails
- Does NOT cleanup worktree (that requires wait.human approval)

Signal Protocol:
- Writes CLOSE_COMPLETE.signal on success with PR URL
- Writes CLOSE_FAILED.signal on failure with error details
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cobuilder.engine.handlers.base import Handler, HandlerRequest
from cobuilder.engine.outcome import Outcome, OutcomeStatus

logger = logging.getLogger(__name__)


class CloseHandler:
    """Handler for programmatic epic closure nodes (``octagon`` shape).

    Automates epic completion by pushing the branch and creating a PR.
    Does NOT cleanup worktree — that requires ``wait.human`` approval.

    Args:
        timeout_s: Maximum seconds for git operations (default: 300).
        default_branch: Default base branch for PR (default: "main").
    """

    def __init__(
        self,
        timeout_s: float = 300.0,
        default_branch: str = "main",
    ) -> None:
        self._timeout_s = timeout_s
        self._default_branch = default_branch

    async def execute(self, request: HandlerRequest) -> Outcome:
        """Push branch, create PR, report completion.

        Args:
            request: HandlerRequest with node, context, run_dir.
                     Node may have attrs:
                     - pr_title: Custom PR title (optional)
                     - pr_body: Custom PR body (optional)
                     - base_branch: Base branch for PR (optional, default: "main")
                     - target_dir: Target repo directory (optional)

        Returns:
            Outcome with status SUCCESS or FAILURE.
        """
        node = request.node
        run_dir = request.run_dir

        # Get configuration from node attributes
        pr_title = node.attrs.get("pr_title")
        pr_body = node.attrs.get("pr_body")
        base_branch = node.attrs.get("base_branch", self._default_branch)
        target_dir = node.attrs.get("target_dir")

        # Determine target directory
        if not target_dir:
            # Fallback to current directory
            target_dir = "."

        target_path = Path(target_dir).resolve()

        # Initialize signals directory
        signals_dir = (Path(run_dir) / "nodes" / node.id / "signals") if run_dir else None
        if signals_dir:
            signals_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Check if we're in a git repo
        if not self._is_git_repo(target_path):
            return self._handle_error(
                signals_dir,
                node.id,
                "Not a git repository",
                {"error_type": "NOT_GIT_REPO", "target_dir": str(target_path)},
            )

        # Step 2: Check if gh CLI is available
        if not self._is_gh_available():
            return self._handle_error(
                signals_dir,
                node.id,
                "GitHub CLI (gh) not available",
                {"error_type": "GH_NOT_AVAILABLE"},
            )

        # Step 3: Get current branch
        try:
            current_branch = self._get_current_branch(target_path)
        except subprocess.CalledProcessError as e:
            return self._handle_error(
                signals_dir,
                node.id,
                f"Failed to get current branch: {e}",
                {"error_type": "GIT_ERROR", "command": "git branch --show-current"},
            )

        # Step 4: Push branch to remote
        try:
            self._push_branch(target_path, current_branch)
            logger.info(
                "CloseHandler: pushed branch '%s' to remote",
                current_branch,
            )
        except subprocess.CalledProcessError as e:
            return self._handle_error(
                signals_dir,
                node.id,
                f"Failed to push branch: {e}",
                {
                    "error_type": "PUSH_FAILED",
                    "branch": current_branch,
                    "stderr": e.stderr.decode() if e.stderr else "",
                },
            )

        # Step 5: Create PR
        try:
            pr_result = self._create_pr(
                target_path,
                current_branch,
                base_branch,
                pr_title,
                pr_body,
            )
            pr_url = pr_result.get("url", "")
            pr_number = pr_result.get("number", 0)
            logger.info(
                "CloseHandler: created PR #%d: %s",
                pr_number,
                pr_url,
            )
        except subprocess.CalledProcessError as e:
            # PR creation failed - branch was already pushed
            return self._handle_error(
                signals_dir,
                node.id,
                f"Failed to create PR: {e}",
                {
                    "error_type": "PR_CREATE_FAILED",
                    "branch": current_branch,
                    "stderr": e.stderr.decode() if e.stderr else "",
                },
            )
        except Exception as e:
            return self._handle_error(
                signals_dir,
                node.id,
                f"Unexpected error creating PR: {e}",
                {
                    "error_type": "PR_CREATE_ERROR",
                    "branch": current_branch,
                },
            )

        # Step 6: Write success signal
        if signals_dir:
            self._write_success_signal(
                signals_dir,
                node.id,
                current_branch,
                pr_url,
                pr_number,
            )

        return Outcome(
            status=OutcomeStatus.SUCCESS,
            context_updates={
                f"${node.id}.branch": current_branch,
                f"${node.id}.pr_url": pr_url,
                f"${node.id}.pr_number": pr_number,
            },
            metadata={
                "branch": current_branch,
                "pr_url": pr_url,
                "pr_number": pr_number,
                "base_branch": base_branch,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_git_repo(self, target_path: Path) -> bool:
        """Check if target_path is a git repository."""
        git_dir = target_path / ".git"
        return git_dir.exists()

    def _is_gh_available(self) -> bool:
        """Check if GitHub CLI is available."""
        return shutil.which("gh") is not None

    def _get_current_branch(self, target_path: Path) -> str:
        """Get the current git branch name."""
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=target_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=int(self._timeout_s),
        )
        return result.stdout.strip()

    def _push_branch(self, target_path: Path, branch: str) -> dict:
        """Push branch to remote with --set-upstream if needed."""
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=target_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=int(self._timeout_s),
        )
        return {"branch": branch, "stdout": result.stdout}

    def _create_pr(
        self,
        target_path: Path,
        branch: str,
        base_branch: str,
        pr_title: str | None,
        pr_body: str | None,
    ) -> dict[str, Any]:
        """Create a PR using gh CLI.

        Returns:
            dict with 'url', 'number', and other PR metadata.
        """
        cmd = [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", branch,
            "--json", "url,number,title,state",
        ]

        if pr_title:
            cmd.extend(["--title", pr_title])
        if pr_body:
            cmd.extend(["--body", pr_body])

        result = subprocess.run(
            cmd,
            cwd=target_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=int(self._timeout_s),
        )

        # Parse JSON output
        pr_data = json.loads(result.stdout)
        return {
            "url": pr_data.get("url", ""),
            "number": pr_data.get("number", 0),
            "title": pr_data.get("title", ""),
            "state": pr_data.get("state", ""),
        }

    def _handle_error(
        self,
        signals_dir: Path | None,
        node_id: str,
        message: str,
        metadata: dict[str, Any],
    ) -> Outcome:
        """Write error signal and return FAILURE outcome."""
        logger.error("CloseHandler: %s", message)

        if signals_dir:
            self._write_error_signal(signals_dir, node_id, message, metadata)

        return Outcome(
            status=OutcomeStatus.FAILURE,
            context_updates={f"${node_id}.error": message},
            metadata=metadata,
        )

    def _write_success_signal(
        self,
        signals_dir: Path,
        node_id: str,
        branch: str,
        pr_url: str,
        pr_number: int,
    ) -> None:
        """Write CLOSE_COMPLETE.signal file."""
        signal_path = signals_dir / "CLOSE_COMPLETE.signal"
        payload = {
            "node_id": node_id,
            "branch": branch,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "status": "success",
        }
        signal_path.write_text(json.dumps(payload, indent=2) + "\n")

    def _write_error_signal(
        self,
        signals_dir: Path,
        node_id: str,
        error_message: str,
        metadata: dict[str, Any],
    ) -> None:
        """Write CLOSE_FAILED.signal file."""
        signal_path = signals_dir / "CLOSE_FAILED.signal"
        payload = {
            "node_id": node_id,
            "error": error_message,
            "status": "failed",
            **metadata,
        }
        signal_path.write_text(json.dumps(payload, indent=2) + "\n")


assert isinstance(CloseHandler(), Handler)