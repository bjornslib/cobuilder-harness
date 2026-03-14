#!/usr/bin/env bash
# zerorepo-pipeline.sh — End-to-end definition pipeline from PRD to executable .dot graph
#
# Chains: zerorepo generate → attractor export → annotate → init-promise → checkpoint → report
#
# Usage:
#   zerorepo-pipeline.sh --prd <PRD-FILE> [OPTIONS]
#
# Options:
#   --prd <path>          Path to PRD markdown file (required)
#   --format <fmt>        Output format (default: attractor)
#   --baseline <path>     Path to baseline JSON (default: .zerorepo/baseline.json)
#   --model <model>       LLM model (default: claude-sonnet-4-5-20250929)
#   --output-dir <dir>    ZeroRepo output directory (default: .zerorepo/output)
#   --skip-annotate       Skip attractor annotate step
#   --skip-promise        Skip init-promise step
#   --dry-run             Print commands without executing
#   -h, --help            Show this help message

set -euo pipefail

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
RUNNER_PY="${SCRIPT_DIR}/zerorepo-run-pipeline.py"
ATTRACTOR_CLI="${PROJECT_ROOT}/.claude/scripts/attractor/cli.py"
PIPELINES_DIR="${PROJECT_ROOT}/.pipelines/pipelines"
CHECKPOINTS_DIR="${PROJECT_ROOT}/.pipelines/checkpoints"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PRD_FILE=""
FORMAT="attractor"
BASELINE="${PROJECT_ROOT}/.zerorepo/baseline.json"
MODEL="claude-sonnet-4-5-20250929"
OUTPUT_DIR="${PROJECT_ROOT}/.zerorepo/output"
SKIP_ANNOTATE=false
SKIP_PROMISE=false
DRY_RUN=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prd)
            PRD_FILE="$2"
            shift 2
            ;;
        --format)
            FORMAT="$2"
            shift 2
            ;;
        --baseline)
            BASELINE="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --skip-annotate)
            SKIP_ANNOTATE=true
            shift
            ;;
        --skip-promise)
            SKIP_PROMISE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "[ERROR] Unknown argument: $1" >&2
            echo "Run '$0 --help' for usage." >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if [[ -z "${PRD_FILE}" ]]; then
    echo "[ERROR] --prd is required." >&2
    echo "Run '$0 --help' for usage." >&2
    exit 2
fi

if [[ ! -f "${PRD_FILE}" ]]; then
    echo "[ERROR] PRD file not found: ${PRD_FILE}" >&2
    exit 2
fi

if [[ ! -f "${RUNNER_PY}" ]]; then
    echo "[ERROR] zerorepo-run-pipeline.py not found: ${RUNNER_PY}" >&2
    exit 2
fi

if [[ ! -f "${ATTRACTOR_CLI}" ]]; then
    echo "[ERROR] attractor cli.py not found: ${ATTRACTOR_CLI}" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# PRD-ID extraction
# ---------------------------------------------------------------------------
PRD_BASENAME="$(basename "${PRD_FILE}")"
PRD_ID="${PRD_BASENAME%.md}"
# If it doesn't look like a PRD reference, use the raw basename
if [[ ! "${PRD_ID}" =~ ^PRD- ]]; then
    PRD_ID="${PRD_BASENAME%.*}"
fi

PIPELINE_DOT="${PIPELINES_DIR}/${PRD_ID}.dot"
CHECKPOINT_JSON="${CHECKPOINTS_DIR}/${PRD_ID}-definition.json"
ZEROREPO_DOT="${OUTPUT_DIR}/pipeline.dot"

# ---------------------------------------------------------------------------
# Helper: run or dry-run a command
# ---------------------------------------------------------------------------
run_cmd() {
    if [[ "${DRY_RUN}" == true ]]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
echo ""
echo "=== ZeroRepo Definition Pipeline ==="
echo "PRD:          ${PRD_FILE}"
echo "PRD-ID:       ${PRD_ID}"
echo "Model:        ${MODEL}"
echo "Output dir:   ${OUTPUT_DIR}"
echo "Pipeline dot: ${PIPELINE_DOT}"
echo "Checkpoint:   ${CHECKPOINT_JSON}"
echo "Skip annotate: ${SKIP_ANNOTATE}"
echo "Skip promise:  ${SKIP_PROMISE}"
echo "Dry run:       ${DRY_RUN}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Ensure zerorepo baseline exists; init if missing
# ---------------------------------------------------------------------------
echo "--- Step 1: Check zerorepo baseline ---"
if [[ ! -f "${BASELINE}" ]]; then
    echo "[INFO] Baseline not found at ${BASELINE}. Running init..."
    run_cmd python3 "${RUNNER_PY}" \
        --operation init \
        --project-path "${PROJECT_ROOT}"
    if [[ "${DRY_RUN}" != true ]] && [[ ! -f "${BASELINE}" ]]; then
        echo "[ERROR] Init completed but baseline still not found: ${BASELINE}" >&2
        exit 1
    fi
else
    echo "[INFO] Baseline found: ${BASELINE}"
fi

# ---------------------------------------------------------------------------
# Step 2: Run zerorepo generate with attractor-pipeline format
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 2: Generate pipeline via zerorepo ---"
export LITELLM_REQUEST_TIMEOUT=1200

run_cmd python3 "${RUNNER_PY}" \
    --operation generate \
    --prd "${PRD_FILE}" \
    --baseline "${BASELINE}" \
    --model "${MODEL}" \
    --output "${OUTPUT_DIR}" \
    --format attractor-pipeline \
    --timeout 1200

if [[ "${DRY_RUN}" != true ]] && [[ ! -f "${ZEROREPO_DOT}" ]]; then
    echo "[ERROR] Expected pipeline.dot not found: ${ZEROREPO_DOT}" >&2
    echo "  Hint: attractor-pipeline format requires 04-rpg.json from generate stage." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3 + 4: Extract PRD-ID (done above) and copy pipeline.dot
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 3/4: Copy pipeline.dot to attractor pipelines dir ---"
run_cmd mkdir -p "${PIPELINES_DIR}"
run_cmd cp "${ZEROREPO_DOT}" "${PIPELINE_DOT}"
echo "[INFO] Pipeline saved: ${PIPELINE_DOT}"

# ---------------------------------------------------------------------------
# Step 4a: Validate pipeline.dot schema
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 4a: Validate pipeline.dot schema ---"
run_cmd python3 "${ATTRACTOR_CLI}" validate "${PIPELINE_DOT}"
echo "[INFO] Validation complete."

# ---------------------------------------------------------------------------
# Step 5: Annotate (cross-reference with beads)
# ---------------------------------------------------------------------------
if [[ "${SKIP_ANNOTATE}" != true ]]; then
    echo ""
    echo "--- Step 5: Annotate pipeline with beads cross-references ---"
    run_cmd python3 "${ATTRACTOR_CLI}" annotate "${PIPELINE_DOT}"
    echo "[INFO] Annotation complete."
else
    echo ""
    echo "--- Step 5: Skipping annotate (--skip-annotate) ---"
fi

# ---------------------------------------------------------------------------
# Step 6: Init completion promise
# ---------------------------------------------------------------------------
if [[ "${SKIP_PROMISE}" != true ]]; then
    echo ""
    echo "--- Step 6: Initialize completion promise ---"
    run_cmd python3 "${ATTRACTOR_CLI}" init-promise "${PIPELINE_DOT}" --execute
    echo "[INFO] Promise initialized."
else
    echo ""
    echo "--- Step 6: Skipping init-promise (--skip-promise) ---"
fi

# ---------------------------------------------------------------------------
# Step 7: Save checkpoint
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 7: Save checkpoint ---"
run_cmd mkdir -p "${CHECKPOINTS_DIR}"
run_cmd python3 "${ATTRACTOR_CLI}" checkpoint save "${PIPELINE_DOT}" --output "${CHECKPOINT_JSON}"
echo "[INFO] Checkpoint saved: ${CHECKPOINT_JSON}"

# ---------------------------------------------------------------------------
# Step 8: Summary report
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 8: Summary report ---"

if [[ "${DRY_RUN}" == true ]]; then
    echo "[dry-run] python3 ${ATTRACTOR_CLI} parse ${PIPELINE_DOT} --output json"
    echo ""
    echo "=== Definition Pipeline Complete ==="
    echo "PRD: ${PRD_ID}"
    echo "Pipeline: ${PIPELINE_DOT}"
    echo "Checkpoint: ${CHECKPOINT_JSON}"
    echo "(Summary skipped in dry-run mode)"
else
    # Parse the DOT file to get structured data for the summary
    PARSE_OUTPUT="$(python3 "${ATTRACTOR_CLI}" parse "${PIPELINE_DOT}" --output json 2>/dev/null || echo '{}')"

    # Use python3 inline to format the summary from JSON
    python3 - <<PYEOF
import json, sys

raw = '''${PARSE_OUTPUT}'''
try:
    data = json.loads(raw)
except Exception:
    data = {}

nodes = data.get("nodes", [])
edges = data.get("edges", [])

# Count by shape/type
shape_counts = {}
worker_counts = {}
for n in nodes:
    attrs = n.get("attrs", {})
    shape = attrs.get("shape", "unknown")
    handler = attrs.get("handler", "")

    # Map shapes to semantic types (handler takes priority over shape)
    handler = attrs.get("handler", "")
    if handler == "codergen":
        key = "codergen (implementation)"
    elif handler == "wait.human":
        key = "wait.human (validation)"
    elif handler == "conditional":
        key = "conditional (decision)"
    elif shape in ("Mdiamond", "Msquare"):
        key = "start/finalize"
    else:
        key = f"{shape} ({handler or 'unknown'})"

    shape_counts[key] = shape_counts.get(key, 0) + 1

    # Worker type distribution
    worker = attrs.get("worker_type", "")
    if worker:
        worker_counts[worker] = worker_counts.get(worker, 0) + 1

total_nodes = len(nodes)
edge_count = len(edges)

print()
print("=== Definition Pipeline Complete ===")
print(f"PRD:        ${PRD_ID}")
print(f"Pipeline:   ${PIPELINE_DOT}")
print(f"Checkpoint: ${CHECKPOINT_JSON}")
print()
print("Node Summary:")
for label, count in sorted(shape_counts.items()):
    print(f"  {label:<30} {count}")
print(f"  {'Total:':<30} {total_nodes}")
print()
if worker_counts:
    print("Worker Type Distribution:")
    for wtype, count in sorted(worker_counts.items()):
        print(f"  {wtype:<35} {count}")
    print()
print(f"Edges: {edge_count}")
print(f"Status: All nodes pending (ready for Stage 2)")
PYEOF
fi

echo ""
echo "=== Pipeline Complete ==="
exit 0
