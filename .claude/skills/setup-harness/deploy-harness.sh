#!/usr/bin/env bash
# deploy-harness.sh — Deploy Claude Code harness to configured targets
#
# Usage:
#   deploy-harness.sh                    Deploy to ALL targets in targets.json
#   deploy-harness.sh --target <path>    Deploy to a single target path
#   deploy-harness.sh --name <name>      Deploy to a named target from targets.json
#   deploy-harness.sh --list             List configured targets
#   deploy-harness.sh --dry-run          Preview rsync without executing
#   deploy-harness.sh --include-mcp      Also copy .mcp.json to target(s)
#
# Options can be combined:
#   deploy-harness.sh --target ~/my-project --dry-run --include-mcp

set -euo pipefail

# ─── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_SOURCE="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TARGETS_FILE="$SCRIPT_DIR/targets.json"

# ─── Defaults ────────────────────────────────────────────────────────────────

DRY_RUN=false
INCLUDE_MCP=false
TARGET_PATH=""
TARGET_NAME=""
LIST_TARGETS=false

# ─── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

ok()   { echo -e "${GREEN}ok${NC} $*"; }
warn() { echo -e "${YELLOW}warn${NC} $*"; }
err()  { echo -e "${RED}error${NC} $*" >&2; }
info() { echo -e "${BLUE}::${NC} $*"; }

# ─── Argument Parsing ────────────────────────────────────────────────────────

usage() {
    cat <<EOF
${BOLD}deploy-harness.sh${NC} — Deploy Claude Code harness to project targets

${BOLD}USAGE${NC}
    deploy-harness.sh [OPTIONS]

${BOLD}OPTIONS${NC}
    --target <path>    Deploy to a single target directory
    --name <name>      Deploy to a named target from targets.json
    --list             List all configured targets
    --dry-run          Preview rsync without executing
    --include-mcp      Also copy .mcp.json to target(s)
    --help             Show this help message

${BOLD}EXAMPLES${NC}
    deploy-harness.sh                                      # Deploy to all targets
    deploy-harness.sh --target ~/Documents/my-project      # Deploy to specific path
    deploy-harness.sh --name zenagent2-agencheck           # Deploy to named target
    deploy-harness.sh --dry-run                            # Preview all deployments
    deploy-harness.sh --target ~/proj --include-mcp        # Deploy with .mcp.json

${BOLD}CONFIG${NC}
    Targets file: $TARGETS_FILE
    Harness source: $HARNESS_SOURCE
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET_PATH="$2"
            shift 2
            ;;
        --name)
            TARGET_NAME="$2"
            shift 2
            ;;
        --list)
            LIST_TARGETS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --include-mcp)
            INCLUDE_MCP=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            err "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# ─── Helper Functions ────────────────────────────────────────────────────────

expand_path() {
    local path="$1"
    # Expand ~ to $HOME
    path="${path/#\~/$HOME}"
    echo "$path"
}

get_targets() {
    # Parse targets.json and return paths
    if [ ! -f "$TARGETS_FILE" ]; then
        err "Targets file not found: $TARGETS_FILE"
        exit 1
    fi
    python3 -c "
import json, sys
with open('$TARGETS_FILE') as f:
    data = json.load(f)
for t in data['targets']:
    print(t['path'])
"
}

get_target_by_name() {
    local name="$1"
    if [ ! -f "$TARGETS_FILE" ]; then
        err "Targets file not found: $TARGETS_FILE"
        exit 1
    fi
    python3 -c "
import json, sys
with open('$TARGETS_FILE') as f:
    data = json.load(f)
for t in data['targets']:
    if t['name'] == '$name':
        print(t['path'])
        sys.exit(0)
print('NOT_FOUND', file=sys.stderr)
sys.exit(1)
"
}

list_targets() {
    if [ ! -f "$TARGETS_FILE" ]; then
        err "Targets file not found: $TARGETS_FILE"
        exit 1
    fi
    echo -e "${BOLD}Configured Deployment Targets${NC}"
    echo ""
    python3 -c "
import json, os
with open('$TARGETS_FILE') as f:
    data = json.load(f)
for t in data['targets']:
    path = t['path'].replace('~', os.path.expanduser('~'))
    exists = os.path.isdir(path)
    status = '\033[0;32mexists\033[0m' if exists else '\033[0;31mmissing\033[0m'
    print(f\"  {t['name']:30s} {path}\")
    print(f\"    {t['description']:30s} [{status}]\")
    print()
"
    echo "Targets file: $TARGETS_FILE"
}

validate_source() {
    if [ ! -d "$HARNESS_SOURCE/.claude" ]; then
        err "Harness source not found at $HARNESS_SOURCE/.claude"
        exit 1
    fi
    if [ ! -f "$HARNESS_SOURCE/.claude/settings.json" ] || [ ! -d "$HARNESS_SOURCE/.claude/skills" ]; then
        err "Invalid harness — missing settings.json or skills/"
        exit 1
    fi

    # Check for stale state files
    local stale_count
    stale_count=$(find "$HARNESS_SOURCE/.claude/state" -type f ! -name .gitkeep 2>/dev/null | wc -l | tr -d ' ')
    if [ "$stale_count" -gt 0 ]; then
        warn "Found $stale_count stale state files in harness source"
    fi

    # Check for stale progress files
    local progress_count
    progress_count=$(find "$HARNESS_SOURCE/.claude/progress" -type f ! -name .gitkeep 2>/dev/null | wc -l | tr -d ' ')
    if [ "$progress_count" -gt 0 ]; then
        warn "Found $progress_count stale progress files in harness source"
    fi
}

# ─── Deploy Function ─────────────────────────────────────────────────────────

deploy_to_target() {
    local target_dir="$1"
    target_dir="$(expand_path "$target_dir")"

    echo ""
    echo -e "${BOLD}━━━ Deploying to: ${target_dir} ━━━${NC}"

    # Validate target exists
    if [ ! -d "$target_dir" ]; then
        err "Target directory does not exist: $target_dir"
        return 1
    fi

    # Check writable
    if [ ! -w "$target_dir" ]; then
        err "No write permission for: $target_dir"
        return 1
    fi

    # Handle existing .claude (symlink vs directory)
    if [ -L "$target_dir/.claude" ]; then
        info "Removing existing .claude symlink -> $(readlink "$target_dir/.claude")"
        if [ "$DRY_RUN" = false ]; then
            rm "$target_dir/.claude"
        fi
    elif [ -d "$target_dir/.claude" ]; then
        info "Updating existing .claude directory"
    fi

    # ── rsync with exclusions ──
    local rsync_flags="-av --delete --delete-excluded"
    if [ "$DRY_RUN" = true ]; then
        rsync_flags="$rsync_flags --dry-run"
        info "DRY RUN — no files will be modified"
    fi

    info "Running rsync..."
    rsync $rsync_flags \
        --exclude='/state/*' \
        --exclude='/completion-state/' \
        --exclude='/progress/*' \
        --exclude='/worker-assignments/*' \
        --exclude='/logs/' \
        --exclude='*.log' \
        --exclude='.DS_Store' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='node_modules/' \
        --exclude='settings.local.json' \
        "$HARNESS_SOURCE/.claude/" "$target_dir/.claude/"

    if [ "$DRY_RUN" = true ]; then
        ok "Dry run complete for $target_dir"
        return 0
    fi

    ok "Copied harness to $target_dir/.claude/"

    # ── Handle .mcp.json ──
    if [ "$INCLUDE_MCP" = true ]; then
        if [ -f "$HARNESS_SOURCE/.mcp.json" ]; then
            cp "$HARNESS_SOURCE/.mcp.json" "$target_dir/.mcp.json"
            ok "Copied .mcp.json (review API keys for this project)"
        else
            warn "No .mcp.json found in harness source"
        fi
    else
        info "Skipping .mcp.json (use --include-mcp to copy)"
    fi

    # ── Create runtime directories with .gitkeep ──
    info "Creating runtime directories..."

    mkdir -p "$target_dir/.claude/state"
    touch "$target_dir/.claude/state/.gitkeep"

    mkdir -p "$target_dir/.claude/completion-state/default"
    mkdir -p "$target_dir/.claude/completion-state/history"
    mkdir -p "$target_dir/.claude/completion-state/promises"
    mkdir -p "$target_dir/.claude/completion-state/sessions"
    touch "$target_dir/.claude/completion-state/.gitkeep"

    mkdir -p "$target_dir/.claude/progress"
    touch "$target_dir/.claude/progress/.gitkeep"

    mkdir -p "$target_dir/.claude/worker-assignments"
    touch "$target_dir/.claude/worker-assignments/.gitkeep"

    ok "Created runtime directories with .gitkeep files"

    # ── Update .gitignore ──
    local gitignore="$target_dir/.gitignore"
    if [ ! -f "$gitignore" ]; then
        touch "$gitignore"
    fi

    if ! grep -q "Claude Code runtime files" "$gitignore" 2>/dev/null; then
        cat >> "$gitignore" << 'GITIGNORE_ENTRIES'

# Claude Code runtime files (not version controlled)
# Directories are kept via .gitkeep, but contents are ignored
.claude/state/*
!.claude/state/.gitkeep
.claude/completion-state/*
!.claude/completion-state/.gitkeep
.claude/progress/*
!.claude/progress/.gitkeep
.claude/worker-assignments/*
!.claude/worker-assignments/.gitkeep
.claude/logs/
.claude/*.log
.claude/settings.local.json
GITIGNORE_ENTRIES
        ok "Updated .gitignore with runtime exclusions"
    else
        ok "Runtime exclusions already in .gitignore"
    fi

    # ── Install git hooks ──
    if git -C "$target_dir" rev-parse --git-dir > /dev/null 2>&1; then
        local hook_source="$target_dir/.claude/hooks/doc-gardener-pre-push.sh"
        if [ -f "$hook_source" ]; then
            local hook_dest git_common_dir
            git_common_dir="$(cd "$target_dir" && git rev-parse --git-common-dir)"
            # Resolve relative path to absolute
            if [[ "$git_common_dir" != /* ]]; then
                git_common_dir="$(cd "$target_dir" && cd "$git_common_dir" && pwd)"
            fi
            hook_dest="$git_common_dir/hooks/pre-push"

            if [ -e "$hook_dest" ] && [ ! -L "$hook_dest" ]; then
                warn "Existing pre-push hook found — skipping (use attractor CLI install-hooks --force)"
            else
                if [ -f "$target_dir/.claude/scripts/attractor/cli.py" ]; then
                    python3 "$target_dir/.claude/scripts/attractor/cli.py" install-hooks 2>/dev/null || true
                fi
            fi

            if [ -L "$hook_dest" ] && [ -x "$hook_dest" ]; then
                ok "Pre-push hook installed (doc-gardener lint)"
            elif [ -e "$hook_dest" ]; then
                ok "Pre-push hook exists (user-managed)"
            else
                info "Pre-push hook not installed"
            fi
        else
            info "Hook source not found — skipping pre-push hook"
        fi
    else
        info "Target is not a git repository — skipping hook installation"
    fi

    # ── Make scripts executable ──
    find "$target_dir/.claude/scripts" -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
    find "$target_dir/.claude/scripts" -type f -name "cs-*" -exec chmod +x {} \; 2>/dev/null || true
    ok "Scripts marked executable"

    # ── Verification ──
    echo ""
    echo -e "${BOLD}Verification${NC}"
    [ -f "$target_dir/.claude/settings.json" ] && ok "settings.json" || warn "settings.json missing"
    [ -d "$target_dir/.claude/skills" ]        && ok "skills/"        || warn "skills/ missing"
    [ -d "$target_dir/.claude/hooks" ]         && ok "hooks/"         || warn "hooks/ missing"
    [ -d "$target_dir/.claude/output-styles" ] && ok "output-styles/" || warn "output-styles/ missing"
    [ -d "$target_dir/.claude/scripts" ]       && ok "scripts/"       || warn "scripts/ missing"

    # Count files deployed
    local file_count
    file_count=$(find "$target_dir/.claude" -type f | wc -l | tr -d ' ')
    ok "Deployed $file_count files to $target_dir/.claude/"

    echo ""
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BOLD}deploy-harness.sh${NC} — Claude Code Harness Deployer"
    echo ""

    # Handle --list
    if [ "$LIST_TARGETS" = true ]; then
        list_targets
        exit 0
    fi

    # Validate source harness
    validate_source
    ok "Harness source validated: $HARNESS_SOURCE"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}DRY RUN MODE — no changes will be made${NC}"
    fi

    # Determine targets
    local targets=()
    local deploy_count=0
    local fail_count=0

    if [ -n "$TARGET_PATH" ]; then
        # Single target from --target
        targets+=("$TARGET_PATH")
    elif [ -n "$TARGET_NAME" ]; then
        # Named target from --name
        local path
        path=$(get_target_by_name "$TARGET_NAME") || {
            err "Target name '$TARGET_NAME' not found in $TARGETS_FILE"
            echo ""
            list_targets
            exit 1
        }
        targets+=("$path")
    else
        # All targets from targets.json
        while IFS= read -r path; do
            targets+=("$path")
        done < <(get_targets)
    fi

    if [ ${#targets[@]} -eq 0 ]; then
        err "No targets configured. Add targets to $TARGETS_FILE"
        exit 1
    fi

    info "Deploying to ${#targets[@]} target(s)"

    # Deploy to each target
    for target in "${targets[@]}"; do
        if deploy_to_target "$target"; then
            deploy_count=$((deploy_count + 1))
        else
            fail_count=$((fail_count + 1))
        fi
    done

    # Summary
    echo ""
    echo -e "${BOLD}━━━ Summary ━━━${NC}"
    ok "$deploy_count target(s) deployed successfully"
    if [ "$fail_count" -gt 0 ]; then
        err "$fail_count target(s) failed"
        exit 1
    fi
}

main "$@"
