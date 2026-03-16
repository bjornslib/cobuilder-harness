#!/bin/bash
# launch_cobuilder.sh — Equivalent to the ccsystem3 zsh function
# Launches Claude Code as a System 3 meta-orchestrator with all required env vars.
#
# Usage:
#   ./launch_cobuilder.sh                    # Default: System 3 mode
#   ./launch_cobuilder.sh --mode orchestrator PRD-NAME  # Orchestrator mode
#   ./launch_cobuilder.sh [extra claude args...]

set -euo pipefail

# Helper: Derive project bank name from current directory
_derive_project_bank() {
    basename "$(pwd)" | tr '[:upper:]' '[:lower:]' | sed 's/_/-/g' | sed 's/ /-/g'
}

MODE="cobuilder-guardian"
PRD_NAME=""
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        *)
            if [[ "$MODE" == "orchestrator" && -z "$PRD_NAME" ]]; then
                PRD_NAME="$1"
            else
                EXTRA_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

# Common exports
export CLAUDE_CODE_ENABLE_TASKS=true
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true
export CLAUDE_PROJECT_BANK="$(_derive_project_bank)"

# Add completion-state scripts to PATH
export PATH="${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/completion-state:$PATH"

if [[ "$MODE" == "cobuilder-guardian" ]]; then
    # System 3 meta-orchestrator mode (equivalent to ccsystem3)
    export CLAUDE_SESSION_ID="system3-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
    export CLAUDE_ENFORCE_PROMISE=true
    export CLAUDE_ENFORCE_BO=true
    export CLAUDE_OUTPUT_STYLE=system3
    export CLAUDE_MAX_ITERATIONS=25

    echo "🚀 Launching CoBuilder (System 3 mode)"
    echo "🆔 Session ID: $CLAUDE_SESSION_ID"
    echo "🧠 Project Bank: $CLAUDE_PROJECT_BANK"
    exec claude --chrome --model claude-opus-4-6 --dangerously-skip-permissions "${EXTRA_ARGS[@]}"

elif [[ "$MODE" == "orchestrator" ]]; then
    # Orchestrator mode (equivalent to ccorch)
    if [[ -z "$PRD_NAME" ]]; then
        echo "❌ Orchestrator mode requires a PRD name: ./launch_cobuilder.sh --mode orchestrator PRD-NAME"
        exit 1
    fi

    export CLAUDE_CODE_TASK_LIST_ID="$PRD_NAME"
    export CLAUDE_SESSION_ID="orch-${PRD_NAME}-$(date -u +%Y%m%dT%H%M%SZ)"
    export CLAUDE_OUTPUT_STYLE=orchestrator
    export CLAUDE_ENFORCE_BO=false
    export CLAUDE_MAX_ITERATIONS=5

    echo "🚀 Launching CoBuilder (Orchestrator mode)"
    echo "🆔 Session ID: $CLAUDE_SESSION_ID"
    echo "🧠 Project Bank: $CLAUDE_PROJECT_BANK"
    echo "📋 Task List ID: $CLAUDE_CODE_TASK_LIST_ID"
    exec claude --chrome --model claude-sonnet-4-6 --dangerously-skip-permissions "${EXTRA_ARGS[@]}"

else
    echo "❌ Unknown mode: $MODE (use 'system3' or 'orchestrator')"
    exit 1
fi
