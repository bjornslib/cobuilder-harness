---
title: "CoBuilder Plugin Migration & Setup Command"
description: "Solution design for converting cobuilder-harness into a Claude Code plugin with /setup command and project-specific file separation"
version: "1.1.0"
last-updated: 2026-03-22
status: active
type: sd
grade: authoritative
---

# SD-COBUILDER-PLUGIN-001: Plugin Migration & Setup Command

## 1. Problem Statement

The cobuilder-harness repository currently deploys via `rsync` (deploy-harness.sh), copying ~550 files into each target project's `.claude/` directory. This approach:

- Requires manual re-deployment on every update
- Copies project-specific files (evidence, targets, hardcoded paths) into generic targets
- Has no proper install/uninstall lifecycle
- Doesn't leverage the Claude Code plugin system (available since early 2026)

## 2. Three Workstreams

| # | Workstream | Scope |
|---|-----------|-------|
| 1 | **Plugin Structure** | Add `.claude-plugin/plugin.json` manifest, restructure directories to match plugin conventions |
| 2 | **`/setup` Command** | Replace `deploy-harness.sh` with a proper `/setup` skill that handles `pip install -e cobuilder` and plugin registration |
| 3 | **Project-Specific Cleanup** | Remove/parameterize files containing hardcoded paths, evidence artifacts, and target-specific references |

---

## 3. Workstream 1: Plugin Structure

### 3.1 Current vs Target Layout

The plugin structure maps almost 1:1 to our existing `.claude/` layout. The only addition is the manifest.

**New file needed:**

```
.claude-plugin/
└── plugin.json          # Plugin manifest (the ONLY new directory)
```

**Existing directories that map directly to plugin conventions:**

| Plugin Convention | Our Existing Path | Status |
|-------------------|-------------------|--------|
| `skills/` | `.claude/skills/` | Already correct |
| `agents/` | `.claude/agents/` | Already correct |
| `hooks/` → `hooks.json` | `.claude/hooks/` + entries in `settings.json` | Needs extraction |
| `commands/` | `.claude/commands/` | Already correct |
| `settings.json` | `.claude/settings.json` | Already correct |
| `.mcp.json` | `.mcp.json` (root) | Needs decision |

### 3.2 Plugin Manifest (`plugin.json`)

```json
{
  "name": "cobuilder",
  "description": "CoBuilder: Multi-agent AI orchestration pipeline with TDD workflows, pipeline execution engine, and 3-level agent hierarchy",
  "version": "0.1.0",
  "author": {
    "name": "CoBuilder Contributors"
  },
  "hooks": "./hooks/hooks.json",
  "mcpServers": "./.mcp.json"
}
```

### 3.3 Hooks Extraction

Currently hooks are defined inline in `.claude/settings.json`. For the plugin, they need to move to a dedicated `hooks.json` file inside `.claude/hooks/`.

**Current** (in `settings.json`):
```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "..." }] }],
    ...
  }
}
```

**Target** (new file `.claude/hooks/hooks.json`):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start-orchestrator-detector.py"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/load-mcp-skills.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/user-prompt-orchestrator-reminder.py"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/gchat-notification-dispatch.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/unified-stop-gate.sh",
            "timeout": 120
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/hindsight-memory-flush.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read|Grep",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/serena_enforce_posttool.py",
            "async": true
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/doc-gardener-pre-push-hook.py",
            "timeout": 65
          }
        ]
      },
      {
        "matcher": "AskUserQuestion",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/gchat-ask-user-forward.py",
            "timeout": 10000
          }
        ]
      },
      {
        "matcher": "Read|Grep",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/serena_enforce_pretool.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Key change**: All paths switch from `$CLAUDE_PROJECT_DIR/.claude/hooks/...` and `/Users/theb/.claude/hooks/...` to `${CLAUDE_PLUGIN_ROOT}/hooks/...`. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` automatically at runtime.

### 3.4 Hook Scripts: Path Resolution Update

Every hook script that references `CLAUDE_PROJECT_DIR` to find sibling files needs updating. The pattern:

**Before:**
```python
hook_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
script_path = os.path.join(hook_dir, ".claude", "hooks", "helper.py")
```

**After:**
```python
# CLAUDE_PLUGIN_ROOT is set automatically for plugin hooks
plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", os.environ.get("CLAUDE_PROJECT_DIR", ""))
script_path = os.path.join(plugin_root, "hooks", "helper.py")
```

This is backward-compatible: falls back to `CLAUDE_PROJECT_DIR` when not running as a plugin.

### 3.5 Settings.json Cleanup

After extracting hooks to `hooks.json`, the `settings.json` becomes leaner:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "permissions": {
    "allow": [
      "Bash(cat:*)",
      "Bash(mkdir:*)",
      "Bash(grep:*)",
      "Bash(git:*)",
      "Bash(npm:*)",
      "Bash(python:*)",
      "Bash(pytest:*)",
      "Bash(task-master:*)"
    ]
  },
  "enabledPlugins": {
    "beads@beads-marketplace": true,
    "frontend-design@claude-plugins-official": true,
    "security-guidance@claude-plugins-official": true,
    "code-review@claude-plugins-official": true
  }
}
```

**Removed from settings.json:**
- `hooks` block → moved to `hooks/hooks.json`
- `statusLine` → user-specific, stays in `settings.local.json`
- Hardcoded Write permission for `/Users/theb/...` path → project-specific

### 3.6 Output Styles

Output styles in `.claude/output-styles/` are **automatically loaded** by Claude Code. In a plugin context, they are still auto-loaded from the plugin's directory — no changes needed.

### 3.7 Implementation Tasks

| Task | Files | Effort |
|------|-------|--------|
| Create `.claude-plugin/plugin.json` | 1 new file | Small |
| Create `.claude/hooks/hooks.json` | 1 new file | Small |
| Update all hook paths to use `${CLAUDE_PLUGIN_ROOT}` | hooks.json + ~12 hook scripts | Medium |
| Remove hooks block from `settings.json` | settings.json | Small |
| Remove project-specific entries from `settings.json` | settings.json | Small |

---

## 4. Workstream 2: `/setup` Command

### 4.1 Purpose

Replace `deploy-harness.sh` with a `/setup` skill that:

1. Installs the `cobuilder` Python package (`pip install -e .` or `pip install cobuilder`)
2. Registers the plugin in the target project's settings
3. Creates runtime directories (`.pipelines/`, `.claude/state/`, etc.)
4. Copies `.mcp.json.example` as a starting point
5. Updates `.gitignore`

### 4.2 Why a Skill, Not deploy-harness.sh

| Aspect | deploy-harness.sh | /setup skill |
|--------|-------------------|-------------|
| Invocation | Manual bash command | `/setup` in any Claude session |
| Discovery | Must know the script exists | Listed in skill registry |
| Plugin install | Not handled | `pip install -e <plugin-root>` |
| Plugin registration | Not handled | Updates target settings.json |
| Interactive | No | AskUserQuestion for options |
| CoBuilder package | Copies providers.yaml only | Full `pip install` |

### 4.3 /setup Skill Design

**File**: `.claude/skills/setup-harness/SKILL.md` (update existing)

The skill replaces the rsync-based approach with plugin-native installation:

#### Step 1: Detect Context

```
Is this being run FROM the harness repo, or FROM a target project?

FROM harness repo → Install mode (deploy plugin to a target)
FROM target project → Already installed, offer re-configure
```

#### Step 2: Install CoBuilder Package

```bash
# From the harness repo root (where pyproject.toml lives)
pip install -e /path/to/cobuilder-harness

# Or if published to PyPI:
pip install cobuilder
```

This makes `from cobuilder.engine import ...` work everywhere — no `sys.path` hacking needed.

#### Step 3: Register Plugin

For project-scope installation (recommended):
```bash
# Claude Code CLI handles this
claude plugin install --scope project --plugin-dir /path/to/cobuilder-harness/.claude
```

Or manually add to target's `.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "cobuilder": true
  }
}
```

#### Step 4: Create Runtime Directories

```bash
mkdir -p .pipelines/pipelines/signals
mkdir -p .pipelines/pipelines/evidence
mkdir -p .claude/state
mkdir -p .claude/progress
mkdir -p .claude/completion-state/{default,history,promises,sessions}
mkdir -p .claude/worker-assignments
```

#### Step 5: Copy Starter Config

```bash
# Copy .mcp.json template if none exists
if [ ! -f .mcp.json ]; then
    cp /path/to/cobuilder-harness/.mcp.json.example .mcp.json
    echo "Created .mcp.json — update API keys before use"
fi
```

#### Step 6: Update .gitignore

Append runtime exclusions (same as current deploy-harness.sh).

### 4.4 Updated SKILL.md Structure

```markdown
# Setup CoBuilder

## Trigger Patterns
- "setup cobuilder", "install cobuilder", "setup harness", "setup plugin"

## Workflow

### Step 1: Determine Install Mode
Question: "How should CoBuilder be installed?"
Options:
1. "Development (pip install -e)" — Editable install, changes reflect immediately
2. "Production (pip install)" — Stable install from package
3. "Plugin only (no Python package)" — Just the Claude Code plugin, no pipeline engine

### Step 2: Install Python Package (if selected)
[Run pip install]

### Step 3: Register Plugin
[Run claude plugin install or update settings.json]

### Step 4: Create Runtime Dirs + .gitignore
[Create directories, update .gitignore]

### Step 5: Configure MCP Servers
Question: "Set up MCP server configuration?"
Options:
1. "Copy template (Recommended)" — Copy .mcp.json.example
2. "Skip" — I'll configure MCP servers manually
```

### 4.5 What Happens to deploy-harness.sh

**Keep it** but mark as legacy. Some users may prefer the bash approach for CI/CD or environments without Claude Code. Add a deprecation notice:

```bash
# DEPRECATED: Use '/setup' skill or 'claude plugin install' instead.
# This script is kept for backward compatibility with CI/CD pipelines.
```

### 4.6 Implementation Tasks

| Task | Files | Effort |
|------|-------|--------|
| Rewrite `setup-harness/SKILL.md` for plugin workflow | 1 file | Medium |
| Create `setup-harness/setup.sh` helper script | 1 new file | Medium |
| Add deprecation notice to `deploy-harness.sh` | 1 file | Small |
| Remove `targets.json` (project-specific) | 1 file delete | Small |

---

## 4b. Optional Extensions Mechanism

### Problem

The plugin ships with ~13 hooks and ~41 skills, but only 4 hooks and 3 skills are core. Users shouldn't be burdened with GChat integration, Serena enforcement, or doc-gardener hooks unless they opt in.

### Solution: Core-Only hooks.json + Documented Opt-In

The `hooks.json` shipped with the plugin includes **only core hooks**:

| Hook | Event | Purpose |
|------|-------|---------|
| `session-start-orchestrator-detector.py` | SessionStart | Orchestrator mode detection |
| `load-mcp-skills.sh` | SessionStart | MCP skills progressive disclosure |
| `user-prompt-orchestrator-reminder.py` | UserPromptSubmit | Orchestrator delegation enforcement |
| `unified-stop-gate.sh` | Stop | Session completion validation |

Extension hooks (GChat, Hindsight, Serena, doc-gardener) remain in the plugin directory but are **not referenced in hooks.json**. Users enable them via `settings.local.json`:

```json
{
  "hooks": {
    "Notification": [{
      "hooks": [{ "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/gchat-notification-dispatch.py" }]
    }],
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{ "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/doc-gardener-pre-push-hook.py", "timeout": 65 }]
    }]
  }
}
```

### Extension Categories

| Category | Hooks | Enable When |
|----------|-------|-------------|
| **GChat Integration** | `gchat-notification-dispatch.py`, `gchat-ask-user-forward.py` | Team uses Google Chat for async notifications |
| **Serena Enforcement** | `serena_enforce_pretool.py`, `serena_enforce_posttool.py` | Project uses Serena for code navigation |
| **Documentation Governance** | `doc-gardener-pre-push-hook.py` | Project enforces documentation standards |
| **Memory Persistence** | `hindsight-memory-flush.py` | Running Hindsight MCP server for long-term memory |

### Optional Skills

All 38 non-core skills ship in the plugin directory but are not auto-loaded (skills require explicit invocation). No mechanism change needed — they are optional by design.

### providers.yaml

`cobuilder/engine/providers.yaml` ships as part of the pip package with current LLM profiles as a working starting point. Users customize per-project via environment variables or by editing the file directly.

---

## 4c. Dead Files — Delete from Repository

Deep research (2026-03-22) identified files/directories with **zero code references** that are historical artifacts. These should be deleted from the repository entirely, not just stripped from the plugin.

### Root-Level Dead Files

| File/Directory | Contents | Evidence |
|---------------|----------|----------|
| `learnings/` | 3 md files (decomposition, coordination, failures) | Zero grep hits across entire codebase |
| `pinchtab/` | Empty directory | Only referenced in 2 old design docs |
| `src/` | `api.py`, `api_endpoint.py` | Test fixture stubs only imported by `tests/test_api_endpoint.py` |
| `state/` | `add_numbers.py`, `test_add_numbers.py`, `ADD-TWO-NUMBERS-bs.md` | Demo artifacts from System 3 showcase |
| `E0-IMPL-PIPELINE-PROGRESS-MONITOR-SUMMARY.md` | Historical summary | Zero incoming references |
| `IMPLEMENTATION_VERIFICATION_E3.md` | Historical verification | References `.claude/progress/` which doesn't exist |
| `API_README.md` | API readme for dead `src/api.py` | Zero references |
| `guardian-workflow.md` | Workflow doc | Duplicate of `.claude/skills/cobuilder-guardian/references/guardian-workflow.md` |
| `phase0-prd-design.md` | PRD design guide | Duplicate of `.claude/skills/cobuilder-guardian/references/phase0-prd-design.md` |
| `settings.json` (root) | Stale copy of `.claude/settings.json` | Diverged — has zenagent-specific webhook, extra hooks. Claude Code reads `.claude/settings.json` |
| `docs-gardener.config.json` (root) | Stale config | Active config at `.claude/scripts/doc-gardener/docs-gardener.config.json` |

### .claude/ Dead Directories

| Directory | Contents | Evidence |
|-----------|----------|----------|
| `.claude/schemas/` | `v3.9-agent-quick-reference.md`, `v3.9-contact-schema.md` (70KB) | Zero code references. Agencheck-communication-agent specific schemas |
| `.claude/narrative/` | `harness-upgrade.md` (825 bytes) | Only referenced by optional hindsight-narrative-logger hook. Stale content |
| `.claude/scripts/attractor/` | 13 Python deprecation wrappers | All files are thin shims with `DeprecationWarning` pointing to `cobuilder/engine/`. Past deprecation expiry date |
| `.claude/user-input-queue/` | `.gitkeep` + `README.md` | Referenced in old PRDs as aspirational. Never actually used by any code |

---

## 5. Workstream 3: Project-Specific File Cleanup

### 5.1 Files to Remove (Project-Specific Artifacts)

These files contain hardcoded paths (`/Users/theb/...`), project names (`zenagent`, `agencheck`), or are runtime evidence from past sessions:

#### 5.1.1 Evidence Directory — DELETE ALL CONTENTS

`.claude/evidence/` — Contains 24 directories of past validation evidence from specific projects. These are runtime artifacts, not harness configuration.

**Action**: Delete all contents, keep directory with `.gitkeep`. Add to `.gitignore`.

```
.claude/evidence/*
!.claude/evidence/.gitkeep
```

#### 5.1.2 Targets Configuration — KEEP & SANITIZE

`.claude/skills/setup-harness/targets.json` — Contains hardcoded paths to specific machines. The file itself is structurally useful as a deploy target registry.

**Action**: Keep the file but replace hardcoded machine paths with generic placeholder entries using `$CLAUDE_PROJECT_DIR`.

#### 5.1.3 Hardcoded Path References — UPDATE

**26 files** reference `/Users/theb/...`. Categorized by action:

| Category | Files | Action |
|----------|-------|--------|
| **Hook scripts** | `session-start-orchestrator-detector.py`, `test-stop-gate.sh` | Replace with `${CLAUDE_PLUGIN_ROOT}` or relative paths |
| **Settings** | `settings.json` (2 hooks use absolute paths) | Handled by Workstream 1 (hooks.json extraction) |
| **Validation docs** | `MONITOR_MODE_QUICK_START.md`, `validation-agent-monitor.py` | Replace paths with generic placeholders |
| **Guardian references** | `gherkin-test-patterns.md`, `path-setup.md`, `generate-manifest.sh` | Replace with relative paths |
| **Evidence** | `pr-213/`, `pr-214/`, R1-R4, REFINE_E1-E4 | Delete (Workstream 5.1.1) |
| **Documentation** | `gardening-report.md`, `SOLUTION-DESIGN-GCHAT-HOOKS-001.md` | Remove project-specific paths |

#### 5.1.4 Project-Name References — UPDATE

**53 files** reference `zenagent` or `agencheck`. Categorized:

| Category | Count | Action |
|----------|-------|--------|
| **Example code in skills/commands** | ~25 | Replace with generic examples (`my-project`, `my-task`) |
| **Test fixtures** | ~10 | Update to use generic names |
| **Documentation** | ~10 | Replace with generic references |
| **Evidence** | ~8 | Delete (covered by 5.1.1) |

### 5.2 Settings That Workers/Pipeline Engine Depend On

The pipeline engine and workers rely on specific settings. These must remain functional after cleanup:

#### 5.2.1 Environment Variables (MUST KEEP)

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

This is required for native Agent Teams. Not project-specific.

#### 5.2.2 Permissions (PARAMETERIZE)

Current permissions include project-specific entries:

```json
"Write(//Users/theb/Documents/Windsurf/zenagent2/...)"  // DELETE - project-specific
```

Generic permissions to keep:
```json
{
  "permissions": {
    "allow": [
      "Bash(cat:*)",
      "Bash(mkdir:*)",
      "Bash(grep:*)",
      "Bash(git:*)",
      "Bash(npm:*)",
      "Bash(python:*)",
      "Bash(pytest:*)",
      "Bash(task-master:*)"
    ]
  }
}
```

#### 5.2.3 Enabled Plugins (KEEP AS-IS)

These are generic plugin references, not project-specific:
```json
{
  "enabledPlugins": {
    "beads@beads-marketplace": true,
    "frontend-design@claude-plugins-official": true,
    "security-guidance@claude-plugins-official": true,
    "code-review@claude-plugins-official": true
  }
}
```

#### 5.2.4 CoBuilder Engine Dependencies

The pipeline engine (`cobuilder/engine/`) depends on:

| Dependency | Current Location | Plugin Behavior |
|------------|-----------------|-----------------|
| `providers.yaml` | `cobuilder/engine/providers.yaml` | Part of pip package — no change needed |
| `.env` (API keys) | `cobuilder/engine/.env` | NOT in plugin. Users create per-project. Add `.env.example` |
| Signal files | `.pipelines/pipelines/signals/` | Created by `/setup`. Runtime-only, gitignored |
| Checkpoint files | `.pipelines/pipelines/*-checkpoint-*.json` | Created by runner. Runtime-only, gitignored |

#### 5.2.5 Hook Dependencies on CLAUDE_PROJECT_DIR

12 hook scripts use `$CLAUDE_PROJECT_DIR` to resolve paths. In plugin mode, `${CLAUDE_PLUGIN_ROOT}` replaces this for finding plugin-internal files. But hooks also need `CLAUDE_PROJECT_DIR` to find project files (e.g., DOT pipelines in `.pipelines/`).

**Resolution**: Use both variables:
- `CLAUDE_PLUGIN_ROOT` → Find hook helpers, scripts, skills (plugin-internal)
- `CLAUDE_PROJECT_DIR` → Find project files, pipelines, workspace (project-scoped)

```python
# Pattern for hook scripts
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR", "")

# Plugin-internal: find sibling scripts
helper = os.path.join(PLUGIN_ROOT, "hooks", "helper.py")

# Project-scoped: find pipeline state
pipelines = os.path.join(PROJECT_DIR, ".pipelines")
```

### 5.3 Files to Keep As-Is

These are generic and don't need changes:

- All skill SKILL.md files (except where they contain hardcoded examples)
- Output styles (`orchestrator.md`, `cobuilder-guardian.md`)
- The entire `cobuilder/` Python package
- `.cobuilder/templates/` (Jinja2 DOT templates)
- `acceptance-tests/` (reference patterns, not project evidence)
- `.pre-commit-config.yaml`
- `pyproject.toml`

### 5.4 Implementation Tasks

| Task | Files | Effort |
|------|-------|--------|
| Delete `.claude/evidence/*` contents, add .gitkeep + .gitignore | ~24 dirs | Small |
| Delete `targets.json`, create `targets.json.example` | 2 files | Small |
| Remove `/Users/theb` from 26 files | 26 files | Medium |
| Replace `zenagent`/`agencheck` examples with generic names | ~30 files | Large |
| Create `cobuilder/engine/.env.example` | 1 new file | Small |
| Update hook scripts to use dual PLUGIN_ROOT/PROJECT_DIR pattern | ~12 files | Medium |

---

## 6. Migration Sequence

Execute in this order to minimize breakage:

### Phase 1: Clean (no functional changes)

1. Delete `.claude/evidence/*` contents
2. Delete `targets.json`, create example
3. Remove hardcoded `/Users/theb` paths from docs and non-functional files
4. Replace `zenagent`/`agencheck` references in examples with generic names
5. Remove project-specific Write permission from `settings.json`

### Phase 2: Plugin Structure

6. Create `.claude-plugin/plugin.json`
7. Create `.claude/hooks/hooks.json` with `${CLAUDE_PLUGIN_ROOT}` paths
8. Remove `hooks` block from `settings.json`
9. Update hook scripts for dual PLUGIN_ROOT/PROJECT_DIR resolution

### Phase 3: Setup Command

10. Rewrite `setup-harness/SKILL.md` for plugin workflow
11. Create `setup-harness/setup.sh` helper
12. Add deprecation notice to `deploy-harness.sh`
13. Create `cobuilder/engine/.env.example`

### Phase 4: Validate

14. Run hook tests: `pytest .claude/tests/hooks/`
15. Test plugin loading: `claude --plugin-dir .claude`
16. Test `/setup` on a clean target project
17. Run pipeline engine tests: `pytest tests/engine/`

---

## 7. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Hook path resolution breaks | Medium | Dual PLUGIN_ROOT/PROJECT_DIR fallback |
| Existing deployments break on update | Low | Keep deploy-harness.sh as legacy |
| `from cobuilder.engine` import fails | Low | `/setup` installs package first |
| Output styles not loaded in plugin mode | Low | Plugin system auto-loads these |
| MCP servers not configured | Medium | `/setup` copies .mcp.json.example |

---

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| Phase 0: Delete dead files | Done | 2026-03-22 | (this PR) |
| Phase 1: Clean | Done | 2026-03-22 | (this PR) |
| Phase 2: Plugin Structure | Remaining | - | - |
| Phase 3: Setup Command | Remaining | - | - |
| Phase 4: Validate | Remaining | - | - |
