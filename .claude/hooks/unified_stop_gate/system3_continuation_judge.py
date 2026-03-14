"""System 3 continuation judge checker using Haiku API for session evaluation.

Only runs for System 3 (system3-*) sessions. Non-System 3 sessions (orchestrators,
workers) skip the judge entirely at the top of check() — they always pass immediately.

CRITICAL: Workers MUST NOT be told to use AskUserQuestion. In native Agent Team
teammates under tmux, AskUserQuestion blocks permanently (permission dialog).

Strictness: Full evaluation with promises, reflection, validation, cleanup checks.
"""

from dataclasses import dataclass
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

Your job: Analyze the last few turns of a System 3 session, the current work state, and ALL task primitives to determine if the session should be allowed to stop.

## Core Principle
The ONLY valid exit for a System 3 session is to have sincerely exhausted all options to continue productive work independently.

## What You Receive
1. WORK STATE: Promises, beads, and ALL task primitives (unfinished AND completed)
2. CONVERSATION: The last few turns of the session transcript

Step 4 has already enforced that no pending/in_progress tasks remain. You are evaluating whether the SESSION ITSELF is properly complete.

## Three-Layer Assessment

### Layer 1: Protocol Compliance
Before stopping, System 3 MUST have completed:
1. **Completion Promises**: All session promises verified with proof (cs-verify --check passed = session-owned promises done), or no promises created. Note: WORK STATE shows only this session's promises after Step 4 filtering — foreign/orphaned promises from other sessions are excluded.
2. **Post-Session Reflection**: Learnings stored to Hindsight (mcp__hindsight__retain)
3. **Validation Evidence**: Business outcomes validated via validation-test-agent (not direct bd close)
4. **Cleanup**: NOTE: Active orchestrator tmux sessions (orch-*) are EXPECTED and are NOT a cleanup issue — they run independently and persist beyond this session.

### Layer 1.5: Validation Integrity (HARD REQUIREMENT)
If the WORK STATE shows ANY of these indicators, ALWAYS BLOCK:
1. **Unvalidated closures**: "closed WITHOUT evidence" → S3 closed tasks without running oversight team
2. **No oversight team**: "NO oversight team found" → S3 never spawned s3-*-oversight validators
3. **Missing closure reports**: Tasks lack .claude/evidence/{id}/closure-report.md

This is CRITICAL RULE #3: System 3 must NEVER close impl_complete tasks without independent validation.
Closing tasks by changing status alone (impl_complete → s3_validating → closed) without spawning
the oversight team is the #1 protocol violation. The evidence directory is the proof of work.

If you see these indicators, respond with should_continue=true and explain the violation.

### Layer 2: Work Availability
Check the WORK STATE for remaining actionable work:
- Unmet promises (owned by this session, not foreign/orphaned) → System 3 MUST continue
- Ready beads (especially P0-P2) → System 3 SHOULD continue
- Open business epics → System 3 SHOULD continue
- If work is available, System 3 should continue unless it genuinely needs user input to decide direction

### Layer 3: Session Exit Validation
Check whether the session has a clear reason to stop:
- Has System 3 completed its assigned work or exhausted available actions?
- Is System 3 blocked on external factors (user input needed, services unavailable)?
- AskUserQuestion is NOT required — System 3 can stop after completing work without presenting options
- If the user explicitly asked to stop, always allow

## Evaluating Completed Tasks
If completed tasks exist, assess whether they represent MEANINGFUL work:
- Did the completed work advance session goals?
- Were tasks substantive (not just "investigate" or "check status")?
- Is the completed work sufficient given the available beads/promises?

## Evaluating Unfinished Tasks (Safety Net)
If somehow unfinished tasks slipped through Step 4, ALWAYS BLOCK:
- Pending/in_progress tasks mean the session has uncommitted work
- Remind System 3 to consider all viable options to continue productive work independently

## Response Format
RESPOND with JSON only:
{"should_continue": boolean, "reason": "brief explanation", "suggestion": "what to do next if continuing"}

should_continue=true means BLOCK the stop (session has more to do)
should_continue=false means ALLOW the stop (session properly completed)

Default to ALLOW (should_continue=false) when:
- The conversation shows the user explicitly asked to stop
- All protocol steps are clearly completed AND work state confirms exhaustion
- System 3 has completed its assigned work and has no more actionable items
- An orchestrator is actively running in a tmux session (this is by design — they persist independently)

Default to BLOCK (should_continue=true) when:
- Active orchestrators are mentioned but COMPLETED work was not validated (note: orchestrators actively RUNNING in tmux are expected and NOT a reason to block)
- Completion promises exist but weren't verified
- No post-session reflection was performed
- Work was started but not validated
- Tasks were closed without evidence (closure-report.md missing)
- No s3-*-oversight team was found despite impl_complete/closed tasks
- Work state shows available high-priority work but System 3 is stopping
- Unfinished tasks exist (remind to continue productive work independently)"""


# Light judge prompt for orchestrators and other sessions
LIGHT_JUDGE_SYSTEM_PROMPT = """You are a session completion evaluator for a Claude Code agent.

Your job: Quickly evaluate whether this agent session has done meaningful work before stopping.

## Key Principle
Be LENIENT. Default to ALLOWING the stop. Only BLOCK if there's clear evidence of:
1. Work that was started but obviously left incomplete mid-task
2. A critical error that the agent acknowledged but didn't address
3. The agent explicitly said it would do something but didn't

## What to IGNORE (do NOT block for these)
- No AskUserQuestion needed (that's a System 3 requirement, not for workers/orchestrators)
- No Hindsight reflection needed
- No completion promises needed
- Available beads/work in the queue (the agent may have finished its assigned scope)
- Cleanup tasks (tmux, message bus) — informational only

## Response Format
RESPOND with JSON only:
{"should_continue": boolean, "reason": "brief explanation", "suggestion": "what to do if continuing"}

should_continue=true means BLOCK (only for obviously incomplete work)
should_continue=false means ALLOW (default — let the session stop)

**Default to should_continue=false (ALLOW stop) in almost all cases.**
Only block if you see clear, unambiguous evidence of abandoned mid-task work."""


class System3ContinuationJudgeChecker:
    """P3.5: Tiered session continuation evaluator using Haiku API.

    Uses Haiku 4.5 to analyze conversation turns and determine if a session
    has properly completed its work before stopping.

    Strictness tiers:
    - System 3 (system3-*): Strict — requires promises, reflection, work exhaustion
    - Orchestrators (orch-*): Light — just checks for obviously incomplete work
    - Other sessions: Light — same as orchestrators

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
        # Determine strictness tier
        self._is_strict = self.config.is_system3  # system3-* = strict, everything else = light

        # CRITICAL FIX (2026-02-15): Non-System 3 sessions MUST skip the judge entirely.
        # The light judge was intended as a lenient safety net, but Haiku ignores the
        # "No AskUserQuestion needed" instruction and returns strict-style responses that
        # tell workers/orchestrators to use AskUserQuestion. In native Agent Team teammates
        # running under tmux-based orchestrators, AskUserQuestion sends a permission
        # request to the team lead that CANNOT be approved via tmux, permanently blocking
        # the session. Skip the judge for ALL non-System 3 sessions to prevent this.
        if not self._is_strict:
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message="Non-System 3 session — judge skipped (workers/orchestrators stop freely)",
                blocking=True,
            )

        # Guard: Check if transcript exists, with fallback to session_id search
        transcript_path = self.session.transcript_path
        if not transcript_path or not os.path.exists(transcript_path):
            # Fallback: try to find transcript using session_id
            try:
                import glob
                session_id = self.session.session_id
                if session_id:
                    # Search for matching transcript in ~/.claude/projects/*/{session_id}.jsonl
                    search_pattern = os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl")
                    matches = glob.glob(search_pattern)
                    if matches:
                        transcript_path = matches[0]  # Use first match
                        print(f"[System3Judge] Found transcript via session_id: {transcript_path}", file=sys.stderr)
            except Exception as e:
                print(f"[System3Judge] Fallback transcript search failed: {e}", file=sys.stderr)

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

        # Guard: Check for API key (ANTHROPIC_API_KEY or DASHSCOPE_API_KEY fallback)
        api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('DASHSCOPE_API_KEY')
        if not api_key:
            return CheckResult(
                priority=Priority.P3_5_SYSTEM3_JUDGE,
                passed=True,
                message="No API key, skipping judge",
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

            # Call Haiku API
            judgment = self._call_haiku_judge(api_key, user_prompt)

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

        # Check GChat communication status (did S3 consult the user?)
        if self._is_strict:
            gchat_status = self._check_gchat_markers()
            prompt_parts.append(
                "## GCHAT COMMUNICATION STATUS\n\n"
                f"{gchat_status['details']}\n\n"
                "Consider carefully:\n"
                "- If the user was asked a question AND replied, their reply should inform "
                "whether stopping is appropriate (e.g., if user said 'end session', allow stop).\n"
                "- If the user was asked a question but hasn't replied yet, S3 should wait for the reply.\n"
                "- If NO question was asked to the user this session, consider whether one SHOULD be asked "
                "before stopping — especially if there's available work or the session accomplished something "
                "the user should be informed about.\n"
                "- GChat questions are equivalent to terminal AskUserQuestion — both reach the user.\n"
            )

        if self._is_strict:
            prompt_parts.append(
                "## KEY QUESTION\n"
                "Has System 3 sincerely exhausted all options to continue productive work "
                "independently? Is there a clear reason the session should stop?\n"
            )
        else:
            prompt_parts.append(
                "## KEY QUESTION\n"
                "Has this agent completed its assigned work? Is there any obviously "
                "incomplete mid-task work that should be finished before stopping?\n"
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

    def _call_haiku_judge(self, api_key: str, user_prompt: str) -> Dict[str, Any]:
        """Call Haiku API to evaluate session continuation.

        Args:
            api_key: Anthropic API key.
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
            # Build client kwargs - include base_url if set (for DASHSCOPE/etc. compatibility)
            client_kwargs: Dict[str, Any] = {"api_key": api_key}
            base_url = os.environ.get("ANTHROPIC_BASE_URL")
            if base_url:
                client_kwargs["base_url"] = base_url

            client = Anthropic(**client_kwargs)

            # Use strict prompt for System 3, light prompt for everything else
            system_prompt = SYSTEM3_JUDGE_SYSTEM_PROMPT if self._is_strict else LIGHT_JUDGE_SYSTEM_PROMPT

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=30.0,  # 30 second timeout
            )

            # Extract text content
            text_content = ''
            for block in response.content:
                if hasattr(block, 'text'):
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
