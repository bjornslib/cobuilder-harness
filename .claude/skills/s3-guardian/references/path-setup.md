---
title: "PATH Setup for Completion State Tools"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# PATH Setup (MANDATORY — Run Once Per Session)

The `cs-promise` and `cs-verify` CLIs live in `.claude/scripts/completion-state/`. Add them to PATH **FIRST, before any other commands**:

```bash
export PATH="${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/completion-state:$PATH"
```

## CRITICAL: PATH is Session-Local

PATH export is **local to the shell session** in which you run it. If you export PATH in one Bash invocation, then run cs-promise in a DIFFERENT invocation, PATH is reset.

**❌ WRONG:**
```bash
Bash(export PATH=... && cs-promise ...

)
Bash(cs-promise --list)  # Fails! PATH lost in new invocation
```

**✅ CORRECT:**
```bash
Bash(export PATH=... && cs-promise --create "..." && cs-promise --list)  # All in ONE invocation
```

## The Complete Init Pattern

For any session using cs-promise (guardian validation, PRD design, etc.):

```bash
#!/bin/bash
set -e  # Exit on error

# 1. MANDATORY FIRST: Set PATH
export PATH="${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/completion-state:$PATH"

# 2. Initialize completion state (creates dir if needed)
cs-init

# 3. Create promise with clear acceptance criteria
cs-promise --create "Design: {initiative}" \
    --ac "Research completed and documented" \
    --ac "PRD written with business goals + epics" \
    --ac "SDs created per epic" \
    --ac "Pipeline created and validated"

# 4. Start the promise (get ID from --list output)
PROMISE_ID=$(cs-promise --list 2>/dev/null | grep "Design: {initiative}" | head -1)
cs-promise --start "$PROMISE_ID"

# 5. Proceed with work (guardian Phases 0-4)
```

## 4 Critical Gotchas

**Gotcha 1: PATH is Session-Local**
- Export in ONE invocation ONLY
- If you need cs-promise across multiple Bash calls, add to `~/.zshrc` globally (not recommended for sessions, but valid for persistent projects)

**Gotcha 2: Piping Without PATH Context**
- ❌ `cs-promise --list 2>/dev/null | tail -20` — might fail with "command not found: tail" if PATH was lost
- ✅ `export PATH=... && cs-promise --list | tail -20` — all in one invocation

**Gotcha 3: CLAUDE_PROJECT_DIR May Be Unset**
- Use fallback: `${CLAUDE_PROJECT_DIR:-.}` expands to current directory (`.`) if unset
- For absolute path (safer): `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/scripts/completion-state:$PATH`

**Gotcha 4: cs-init Must Run BEFORE cs-promise Commands**
- Order: PATH export → cs-init → cs-promise --create
- Without cs-init, completion-state directory may not exist (though cs-promise --create creates it)

## Debugging Checklist (If "command not found: cs-promise")

1. ✅ **Verify PATH is set:** `echo $PATH | grep completion-state` — should show path segment
2. ✅ **Check file exists:** `ls -la .claude/scripts/completion-state/cs-promise` — should exist with execute bit
3. ✅ **Test which:** `which cs-promise` — should return the script path
4. ✅ **Same invocation:** Are you calling cs-promise in the SAME Bash invocation where you set PATH?

## Why This Fails Without PATH

`cs-promise` is a script at `.claude/scripts/completion-state/cs-promise`, not a system-wide command. Without the export, the shell cannot find it. Error: `command not found: cs-promise`.
