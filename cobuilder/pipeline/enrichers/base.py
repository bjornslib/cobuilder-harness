"""Base enricher class for the LLM enrichment pipeline."""
import os
import re
import logging
import anthropic
import yaml

logger = logging.getLogger(__name__)


def _sanitize_yaml(raw: str) -> str:
    """Attempt to fix common LLM-generated YAML issues.

    The most frequent failure mode is unquoted string values that contain
    colons (e.g. ``globals: true`` inside a longer description).  This
    function quotes such values so ``yaml.safe_load`` can parse them.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        # Skip blank lines, comments, list-only lines
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            # For list items like "- some: value: thing", check for issues
            if stripped.startswith("- "):
                item = stripped[2:]
                # If the list item itself looks like "key: value" with extra
                # colons in the value portion, quote the value.
                m = re.match(r'^(\s*-\s*)(\w[\w\s]*?):\s+(.+)$', line)
                if m:
                    prefix, key, val = m.group(1), m.group(2), m.group(3)
                    # If the value contains an unquoted colon, quote it
                    if ':' in val and not (val.startswith('"') or val.startswith("'")):
                        line = f'{prefix}{key}: "{val}"'
            lines.append(line)
            continue

        # Match "key: value" pattern
        m = re.match(r'^(\s*)(\w[\w\s]*?):\s+(.+)$', line)
        if m:
            indent, key, val = m.group(1), m.group(2), m.group(3)
            # If the value contains a colon and isn't already quoted, quote it
            if ':' in val and not (val.startswith('"') or val.startswith("'")):
                # Escape any existing double quotes in the value
                val_escaped = val.replace('"', '\\"')
                line = f'{indent}{key}: "{val_escaped}"'
        lines.append(line)

    return "\n".join(lines)


class BaseEnricher:
    """Base class for all node enrichers.

    Each enricher makes LLM calls to append structured data to pipeline nodes.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.client = anthropic.Anthropic()

    def enrich_all(self, nodes: list[dict], repomap: dict, sd: str) -> list[dict]:
        """Enrich all nodes in the list."""
        return [self._enrich_one(node, repomap, sd) for node in nodes]

    def _enrich_one(self, node: dict, repomap: dict, sd: str) -> dict:
        """Enrich a single node. Must be overridden by subclasses."""
        raise NotImplementedError

    def _call_llm(self, prompt: str) -> str:
        """Make a single LLM call and return the response text."""
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    def _warn_if_empty(self, parsed: dict, required_key: str, node_title: str) -> None:
        """Log a warning if the parsed result is missing the expected key."""
        if not parsed or required_key not in parsed:
            logger.warning(
                "[%s] Enrichment returned no '%s' for node '%s' — using defaults",
                self.__class__.__name__,
                required_key,
                node_title,
            )

    def _parse_yaml(self, text: str, *, _retries: int = 1) -> dict:
        """Extract YAML block from response text with sanitization and retry.

        Parse strategy (in order):
        1. Try ``yaml.safe_load`` on the raw extracted block.
        2. If that fails, sanitize the YAML (quote unquoted string values
           containing colons) and try again.
        3. If that also fails, ask the LLM to fix the YAML (*_retries* times).
        4. Return ``{}`` if all attempts fail.
        """
        match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
        if not match:
            return {}

        raw_yaml = match.group(1)

        # --- Attempt 1: raw parse ---
        try:
            return yaml.safe_load(raw_yaml) or {}
        except yaml.YAMLError:
            pass  # fall through to sanitization

        # --- Attempt 2: sanitize and parse ---
        sanitized = _sanitize_yaml(raw_yaml)
        try:
            result = yaml.safe_load(sanitized) or {}
            if result:
                logger.info("YAML sanitization succeeded")
                return result
        except yaml.YAMLError as e:
            parse_error = str(e)
            logger.warning("YAML parse failed after sanitization: %s", parse_error)

        # --- Attempt 3: LLM retry ---
        for attempt in range(1, _retries + 1):
            logger.info("Retrying YAML via LLM (attempt %d/%d)", attempt, _retries)
            fix_prompt = (
                "The following YAML block failed to parse:\n\n"
                f"```yaml\n{raw_yaml}```\n\n"
                f"Parse error: {parse_error}\n\n"
                "Return ONLY the corrected YAML inside a ```yaml``` code fence. "
                "All string values containing colons MUST be wrapped in double quotes."
            )
            try:
                fixed_text = self._call_llm(fix_prompt)
                fixed_match = re.search(r"```yaml\n(.*?)```", fixed_text, re.DOTALL)
                if fixed_match:
                    result = yaml.safe_load(fixed_match.group(1))
                    if result:
                        logger.info("YAML LLM fix succeeded on attempt %d", attempt)
                        return result
            except (yaml.YAMLError, Exception) as retry_err:
                logger.warning("YAML LLM fix attempt %d failed: %s", attempt, retry_err)

        logger.error("YAML parse failed after all attempts, returning empty dict")
        return {}
