"""System 3 continuation judge checker using Haiku API for session evaluation.

Only runs for System 3 (system3-*) sessions. Non-System 3 sessions (orchestrators,
workers) skip the judge entirely at the top of check() — they always pass immediately.

CRITICAL: Workers MUST NOT be told to use AskUserQuestion. In native Agent Team
teammates under tmux, AskUserQuestion blocks permanently (permission dialog).

Strictness: Full evaluation with promises, reflection, validation, cleanup checks.
"""

import json
import os
import sys
from typing import Optional, List, Dict, Any

from .config import CheckResult, EnvironmentConfig, Priority
from .checkers import SessionInfo


def _extract_json_object(text: str) -> str:
    """Extract the outermost JSON object from text that may contain extra content.

    Handles cases where Haiku returns JSON followed by explanatory text:
        {"should_continue": true, ...}

        Note: The session has properly...

    Returns just the JSON substring between the first '{' and its matching '}'.
    Raises ValueError if no valid JSON object structure is found.
    """
    start = text.find('{')
    if start == -1:
        raise ValueError("No '{' found in response text")

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    raise ValueError(f"Unbalanced braces in response (depth={depth} at end)")


# System prompt for the Haiku judge
SYSTEM3_JUDGE_SYSTEM_PROMPT = """You are a session completion evaluator for a System 3 meta-orchestrator.

System 3 operates in SDK mode: it launches pipeline_runner.py which dispatches AgentSDK workers
via DOT pipeline files. Workers run as background subprocesses (not tmux). Work is tracked via
beads (bd) and session promises (cs-promise/cs-verify).

## Core Principle
The ONLY valid exit for a System 3 session is to have sincerely exhausted all options to
continue productive work independently, OR the user explicitly asked to stop.

## What You Receive
1. WORK STATE: Session promises, beads, and task primitives
2. CONVERSATION: The last few turns of the session transcript

## Assessment

### Layer 1: Protocol Compliance
Before stopping, System 3 MUST have:
1. **Completion Promises**: All session promises verified (cs-verify --check passed), or none created.
2. **Post-Session Reflection**: Learnings stored to Hindsight (mcp__hindsight__retain).
3. **Pipeline State**: Any active pipelines (pipeline_runner.py) have reached a terminal state
   or are intentionally left running (e.g. long-running background workers with monitoring in place).

### Layer 2: Work Availability
- Unmet promises owned by this session → System 3 MUST continue
- Ready beads (P0-P2) with no external blockers → System 3 SHOULD continue
- Pipeline nodes stuck in pending/active without a monitor → System 3 SHOULD continue
- If the user asked to stop, ALWAYS allow regardless of available work

### Layer 3: Session Exit
- Has System 3 completed its assigned goal or genuinely exhausted available actions?
- Is it blocked on an external factor (user decision needed, service unavailable)?

## ALLOW stop when:
- User explicitly asked to stop
- All promises verified, Hindsight retention done, no high-priority beads unblocked
- Work completed and properly validated via validation-test-agent

## BLOCK stop when:
- Session promises exist but cs-verify was not run
- Hindsight retention (mcp__hindsight__retain) was not called this session
- Unfinished tasks slipped through (pending/in_progress in work state)
- High-priority (P0-P2) beads are ready and System 3 has not addressed them
- Work was started but left visibly incomplete mid-task
- **Background pipeline monitor launched**: If the transcript shows a pipeline monitor
  launched with `run_in_background=True` (or `run_in_background: true`), this is a
  protocol violation. Pipeline monitors MUST be blocking (`run_in_background=False`).
  Background monitors detach from System 3, leaving the pipeline unmonitored. BLOCK
  and suggest relaunching as a blocking monitor.
- **Guardian Phase 4 skipped**: A pipeline DOT file exists with all codergen nodes at
  accepted/validated, BUT the conversation does NOT contain evidence of running independent
  Gherkin acceptance tests (acceptance-tests/PRD-*/). Phase 4 validation is MANDATORY after
  pipeline completion — the guardian must score implementations against blind tests that
  workers never saw. Look for: validation-test-agent invocation, Gherkin scenario scoring,
  or explicit "Phase 4" references in the transcript. If absent, BLOCK with suggestion to
  run Phase 4 before closing.

## Response Format
Your response MUST be a JSON object and nothing else. Start with { and end with }.
{"should_continue": boolean, "reason": "brief explanation", "suggestion": "what to do next if continuing"}

should_continue=true means BLOCK the stop
should_continue=false means ALLOW the stop"""


class System3ContinuationJudgeChecker:
    """P3.5: Session continuation evaluator using LLM API.

    Runs only for System 3 (system3-*) sessions. All other sessions skip
    this check and stop freely.

    Fails open on any errors to avoid blocking valid stops.
    """

    def __init__(self, config: EnvironmentConfig, session: SessionInfo):
        """Initialize the checker.

        Args:
            config: Environment configuration (provides is_system3 check).
            session: Session info with transcript path.
        """
        self.config = config
        self.session = session

    def check(self) -> CheckResult:
        """Check if System 3 session should be allowed to stop.

        Returns:
            CheckResult with:
            - passed=True if not System3, no transcript, judge approves, or error (fail-open)
            - passed=False if judge blocks stop (session has more work to do)
        """
        # Only run for System 3 sessions — all other sessions stop freely
        if not self.config.is_system3:
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message="Non-System 3 session — judge skipped",
                blocking=True,
            )

        # Guard: Check if transcript exists.
        # Claude Code passes transcript_path as a common field in all hook inputs.
        # The shell script exports it via CLAUDE_HOOK_INPUT → SessionInfo.from_hook_input().
        transcript_path = self.session.transcript_path
        print(f"[System3Judge] transcript_path from hook input: {transcript_path!r}", file=sys.stderr)
        if not transcript_path or not os.path.exists(transcript_path):
            # Fallback 1: search by session_id (works when hook input session_id == transcript filename UUID)
            try:
                import glob
                session_id = self.session.session_id
                if session_id and session_id != 'unknown':
                    search_pattern = os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl")
                    matches = glob.glob(search_pattern)
                    if matches:
                        transcript_path = matches[0]
                        print(f"[System3Judge] Found transcript via session_id fallback: {transcript_path}", file=sys.stderr)
            except Exception as e:
                print(f"[System3Judge] session_id fallback failed: {e}", file=sys.stderr)

        if not transcript_path or not os.path.exists(transcript_path):
            # Fallback 2: most recently modified .jsonl in the project's transcript dir.
            # CLAUDE_SESSION_ID (system3-*) != transcript UUID filename, so session_id search
            # fails. The most recently modified transcript is the current session.
            try:
                import glob
                project_dir = os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())
                safe_project = project_dir.replace('/', '-').lstrip('-')
                search_pattern = os.path.expanduser(f"~/.claude/projects/-{safe_project}/*.jsonl")
                matches = sorted(glob.glob(search_pattern), key=os.path.getmtime, reverse=True)
                if matches:
                    transcript_path = matches[0]
                    print(f"[System3Judge] Found transcript via most-recent fallback: {transcript_path}", file=sys.stderr)
            except Exception as e:
                print(f"[System3Judge] most-recent fallback failed: {e}", file=sys.stderr)

        # Final check: if still no transcript, skip judge
        if not transcript_path or not os.path.exists(transcript_path):
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message="No transcript available, skipping judge",
                blocking=True,
            )

        # Update session with found transcript path
        self.session.transcript_path = transcript_path

        # Resolve judge LLM config from providers.yaml (judge_profile key)
        judge_config = self._resolve_judge_config()
        if not judge_config.get('api_key'):
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message="No API key for judge profile, skipping judge",
                blocking=True,
            )

        # Main evaluation wrapped in try/except for fail-open behavior
        try:
            # Extract last 5 conversation turns
            turns = self._extract_last_turns(self.session.transcript_path, num_turns=5)

            if not turns:
                return CheckResult(
                    priority=Priority.P3_5_SYSTEM3_JUDGE,
                    passed=True,
                    message="No conversation turns found in transcript",
                    blocking=True,
                )

            # Build evaluation prompt
            user_prompt = self._build_evaluation_prompt(turns)

            # Call judge API using resolved config
            judgment = self._call_haiku_judge(judge_config, user_prompt)

            # Parse response
            should_continue = judgment.get('should_continue', False)
            reason = judgment.get('reason', 'No reason provided')
            suggestion = judgment.get('suggestion', '')

            # Return result based on judgment
            if should_continue:
                # BLOCK - session should continue
                message = f"System 3 Judge: {reason}"
                if suggestion:
                    message += f"\n\nSuggestion: {suggestion}"
                return CheckResult(
                    priority=Priority.P3_5_SYSTEM3_JUDGE,
                    passed=False,
                    message=message,
                    blocking=True,
                )
            else:
                # ALLOW - session can stop
                return CheckResult(
                    priority=Priority.P3_5_SYSTEM3_JUDGE,
                    passed=True,
                    message=f"System 3 Judge approves stop: {reason}",
                    blocking=True,
                )

        except Exception as e:
            # Fail-open on any error
            error_msg = str(e)[:200]  # Truncate long errors
            print(f"[System3Judge] Error during evaluation: {error_msg}", file=sys.stderr)
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message=f"Judge error (fail-open): {error_msg}",
                blocking=True,
            )

    def _extract_last_turns(self, transcript_path: str, num_turns: int = 5) -> List[Dict[str, Any]]:
        """Extract the last N user/assistant turns from a JSONL transcript.

        Args:
            transcript_path: Path to the JSONL transcript file.
            num_turns: Number of turns to extract (default: 5).

        Returns:
            List of turn dictionaries with 'role' and 'content_summary' keys.

        Raises:
            Exception: On file read errors or JSON parsing errors.
        """
        turns = []

        try:
            with open(transcript_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines

                    entry_type = entry.get('type')
                    if entry_type not in ('user', 'assistant'):
                        continue

                    # Extract content based on role
                    role = entry_type
                    content_summary = self._extract_content_summary(entry, role)

                    if content_summary:
                        turns.append({
                            'role': role,
                            'content_summary': content_summary
                        })

            # Return last N turns
            return turns[-num_turns:] if len(turns) > num_turns else turns

        except Exception as e:
            print(f"[System3Judge] Error reading transcript: {e}", file=sys.stderr)
            raise

    def _extract_content_summary(self, entry: Dict[str, Any], role: str) -> str:
        """Extract and summarize content from a transcript entry.

        Args:
            entry: The transcript entry dictionary.
            role: The role ('user' or 'assistant').

        Returns:
            Summarized content string (max ~600 chars).
        """
        message = entry.get('message', {})
        content = message.get('content', '')

        parts = []

        if role == 'user':
            # User content can be string or list
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        parts.append(block.get('text', ''))
                    elif isinstance(block, str):
                        parts.append(block)

        elif role == 'assistant':
            # Assistant content is typically a list of content blocks
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get('type')
                        if block_type == 'text':
                            parts.append(block.get('text', ''))
                        elif block_type == 'tool_use':
                            tool_name = block.get('name', 'unknown')
                            # Summarize tool input
                            tool_input = block.get('input', {})
                            input_summary = self._summarize_tool_input(tool_input)
                            parts.append(f"[Tool: {tool_name}({input_summary})]")
            elif isinstance(content, str):
                parts.append(content)

        # Join and truncate to ~600 chars
        full_content = ' '.join(parts)
        max_len = 600
        if len(full_content) > max_len:
            return full_content[:max_len] + '...'
        return full_content

    def _summarize_tool_input(self, tool_input: Dict[str, Any]) -> str:
        """Summarize tool input for display.

        Args:
            tool_input: Dictionary of tool input parameters.

        Returns:
            Brief summary string (max ~50 chars).
        """
        if not tool_input:
            return ''

        # Try to find key parameters
        key_params = []
        for key in ['file_path', 'pattern', 'command', 'skill', 'prompt', 'message']:
            if key in tool_input:
                value = str(tool_input[key])
                if len(value) > 40:
                    value = value[:40] + '...'
                key_params.append(f"{key}={value}")
                if len(key_params) >= 2:
                    break

        if key_params:
            return ', '.join(key_params)

        # Fallback: show first key
        first_key = next(iter(tool_input.keys()), None)
        if first_key:
            value = str(tool_input[first_key])
            if len(value) > 40:
                value = value[:40] + '...'
            return f"{first_key}={value}"

        return 'no params'

    def _build_evaluation_prompt(self, turns: List[Dict[str, Any]]) -> str:
        """Build the evaluation prompt from conversation turns and work state.

        Structure: Work state FIRST (decision-relevant data), then conversation.
        The judge should see the full picture before reading the transcript.

        Args:
            turns: List of turn dictionaries with 'role' and 'content_summary'.

        Returns:
            Formatted prompt string for the Haiku judge.
        """
        parts = []
        for turn in turns:
            role = turn.get('role', 'unknown').upper()
            content = turn.get('content_summary', '')
            parts.append(f"[{role}]: {content}")

        conversation = "\n\n".join(parts)

        # Work state from Step 4 (includes ALL task states)
        work_state = os.environ.get('WORK_STATE_SUMMARY', '').strip()

        # Build prompt with work state FIRST for prominence
        prompt_parts = ["Evaluate this System 3 session for completion readiness.\n"]

        if work_state:
            prompt_parts.append(f"## WORK STATE AND TASK PRIMITIVES\n\n{work_state}\n")

        # GChat communication status (did S3 consult the user?)
        gchat_status = self._check_gchat_markers()
        prompt_parts.append(
            "## GCHAT COMMUNICATION STATUS\n\n"
            f"{gchat_status['details']}\n\n"
            "- If the user replied to a question, their reply informs whether stopping is appropriate.\n"
            "- If a question was asked but not yet replied to, System 3 should wait.\n"
        )

        prompt_parts.append(
            "## KEY QUESTION\n"
            "Has System 3 sincerely exhausted all options to continue productive work "
            "independently? Is there a clear reason the session should stop?\n"
        )

        prompt_parts.append(f"## CONVERSATION (last turns)\n\n{conversation}")

        return "\n".join(prompt_parts)

    def _check_gchat_markers(self) -> Dict[str, Any]:
        """Check GChat-forwarded AskUserQuestion markers for this session.

        Marker files at .claude/state/gchat-forwarded-ask/{question_id}.json are written
        by the gchat-ask-user-forward.py PreToolUse hook when it blocks an interactive
        AskUserQuestion and forwards the question to Google Chat instead.

        Returns a dict with:
            - asked: bool — whether any question was forwarded to GChat this session
            - answered: bool — whether the user replied to any forwarded question
            - details: str — human-readable summary for the judge prompt
        """
        import json as _json

        project_dir = os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())
        session_id = os.environ.get('CLAUDE_SESSION_ID', '')
        marker_dir = os.path.join(project_dir, '.claude', 'state', 'gchat-forwarded-ask')

        result = {"asked": False, "answered": False, "details": ""}

        if not os.path.exists(marker_dir):
            result["details"] = "No GChat markers directory found — no questions forwarded to GChat this session."
            return result

        asked_count = 0
        resolved_count = 0
        pending_count = 0
        latest_question = ""
        latest_answer = ""

        try:
            for filename in os.listdir(marker_dir):
                if not filename.endswith('.json'):
                    continue
                filepath = os.path.join(marker_dir, filename)
                try:
                    with open(filepath) as f:
                        marker_data = _json.load(f)
                    if marker_data.get('session_id') != session_id:
                        continue
                    asked_count += 1
                    status = marker_data.get('status', 'pending')
                    if status == 'resolved':
                        resolved_count += 1
                        latest_answer = marker_data.get('answer', marker_data.get('response', ''))
                    else:
                        pending_count += 1
                    # Track the latest question text
                    questions = marker_data.get('questions', [])
                    if questions:
                        latest_question = questions[0].get('question', '')
                except (OSError, _json.JSONDecodeError):
                    continue
        except Exception as e:
            print(f"[System3Judge] Error checking GChat markers: {e}", file=sys.stderr)

        result["asked"] = asked_count > 0
        result["answered"] = resolved_count > 0

        if asked_count == 0:
            result["details"] = "No GChat questions were forwarded to the user during this session."
        else:
            parts = [f"{asked_count} question(s) forwarded to GChat this session."]
            if resolved_count > 0:
                parts.append(f"{resolved_count} answered by user.")
                if latest_answer:
                    parts.append(f"Latest user reply: \"{latest_answer}\"")
            if pending_count > 0:
                parts.append(f"{pending_count} still awaiting reply.")
            if latest_question:
                parts.append(f"Latest question asked: \"{latest_question}\"")
            result["details"] = " ".join(parts)

        print(f"[System3Judge] GChat markers: asked={asked_count}, resolved={resolved_count}, pending={pending_count}", file=sys.stderr)
        return result

    def _resolve_judge_config(self) -> Dict[str, Any]:
        """Resolve the judge LLM config from providers.yaml.

        Reads the ``judge_profile`` key from ``cobuilder/engine/providers.yaml``
        and resolves env-var references ($VAR) in ``api_key``.

        Returns:
            Dict with 'model', 'api_key', and 'base_url' keys.
            Falls back to env vars / hardcoded defaults if providers.yaml
            is unavailable.
        """
        import re

        _env_pattern = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")

        def _resolve(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            m = _env_pattern.match(value)
            if m:
                return os.environ.get(m.group(1))
            return value

        # Try to load providers.yaml from cobuilder/engine/ (next to providers.py)
        try:
            import yaml

            project_dir = os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())
            providers_path = os.path.join(project_dir, 'cobuilder', 'engine', 'providers.yaml')

            if os.path.exists(providers_path):
                with open(providers_path) as f:
                    raw = yaml.safe_load(f)

                judge_profile_name = raw.get('judge_profile') or raw.get('default_profile')
                profiles = raw.get('profiles', {})

                if judge_profile_name and judge_profile_name in profiles:
                    profile = profiles[judge_profile_name]
                    config = {
                        'model': profile.get('model', 'glm-5'),
                        'api_key': _resolve(profile.get('api_key')),
                        'base_url': profile.get('base_url', 'https://api.anthropic.com'),
                    }
                    print(
                        f"[System3Judge] Using judge_profile '{judge_profile_name}' "
                        f"(model={config['model']}, base_url={config['base_url']})",
                        file=sys.stderr,
                    )
                    return config
        except Exception as e:
            print(f"[System3Judge] Failed to load providers.yaml: {e}", file=sys.stderr)

        # Fallback: env vars (legacy behavior)
        print("[System3Judge] Falling back to environment variables for judge config", file=sys.stderr)
        return {
            'model': os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-4-5-20251001'),
            'api_key': os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('DASHSCOPE_API_KEY'),
            'base_url': os.environ.get('ANTHROPIC_BASE_URL'),
        }

    def _call_haiku_judge(self, judge_config: Dict[str, Any], user_prompt: str) -> Dict[str, Any]:
        """Call the judge LLM to evaluate session continuation.

        Args:
            judge_config: Dict with 'model', 'api_key', and 'base_url' from
                _resolve_judge_config().
            user_prompt: The evaluation prompt with conversation context.

        Returns:
            Dictionary with 'should_continue', 'reason', and 'suggestion' keys.

        Raises:
            Exception: On API errors, timeout, or response parsing errors.
        """
        try:
            # Import Anthropic SDK (lazy import to avoid dependency issues)
            from anthropic import Anthropic
        except ImportError as e:
            raise Exception(f"Anthropic SDK not available: {e}")

        try:
            # Build client kwargs from resolved judge config
            client_kwargs: Dict[str, Any] = {"api_key": judge_config['api_key']}
            base_url = judge_config.get('base_url')
            if base_url:
                client_kwargs["base_url"] = base_url

            client = Anthropic(**client_kwargs)

            system_prompt = SYSTEM3_JUDGE_SYSTEM_PROMPT

            model = judge_config['model']

            response = client.messages.create(
                model=model,
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=75.0,  # 75 second timeout (shell limit is 90s)
            )

            # Extract text content (only TextBlock has .text; other block types are skipped)
            from anthropic.types import TextBlock
            text_content = ''
            for block in response.content:
                if isinstance(block, TextBlock):
                    text_content += block.text

            if not text_content:
                raise Exception("No text content in Haiku response")

            # Strip markdown code fences if present
            clean_text = text_content.strip()
            if clean_text.startswith('```'):
                # Remove opening fence (```json or ```)
                first_newline = clean_text.index('\n')
                clean_text = clean_text[first_newline + 1:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

            # Extract just the JSON object (handles trailing text from Haiku)
            try:
                json_str = _extract_json_object(clean_text)
            except ValueError as e:
                raise Exception(f"Could not extract JSON from Haiku response: {e}")

            # Parse JSON response
            judgment = json.loads(json_str)

            # Validate required fields
            if 'should_continue' not in judgment:
                raise Exception("Missing 'should_continue' in judgment response")

            # Ensure all expected fields exist (with defaults)
            result = {
                'should_continue': bool(judgment.get('should_continue', False)),
                'reason': judgment.get('reason', 'No reason provided'),
                'suggestion': judgment.get('suggestion', ''),
            }

            return result

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse Haiku JSON response: {e}")
        except Exception as e:
            # Re-raise with context
            raise Exception(f"Haiku API call failed: {e}")
