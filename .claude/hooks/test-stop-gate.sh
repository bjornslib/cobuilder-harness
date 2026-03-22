#!/bin/bash
# Test script for unified stop gate
# Tests all 6 verification scenarios from the plan

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
STOP_GATE="$PROJECT_ROOT/.claude/hooks/unified-stop-gate.sh"
CS_SCRIPTS="$PROJECT_ROOT/.claude/scripts/completion-state"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_count=0
pass_count=0
fail_count=0

run_test() {
    local test_name="$1"
    local expected_result="$2"  # "approve" or "block"
    local setup_fn="$3"

    test_count=$((test_count + 1))
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Test $test_count: $test_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Run setup
    if [ -n "$setup_fn" ]; then
        echo "Setup: Running $setup_fn"
        eval "$setup_fn"
    fi

    # Run stop gate
    echo "Executing stop gate..."
    START_TIME=$(date +%s)
    RESULT=$(echo '{}' | bash "$STOP_GATE" 2>&1)
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Parse decision
    DECISION=$(echo "$RESULT" | jq -r '.decision // "unknown"')
    MESSAGE=$(echo "$RESULT" | jq -r '.systemMessage // .reason // ""')

    # Check result
    if [ "$DECISION" = "$expected_result" ]; then
        echo -e "${GREEN}✅ PASS${NC}: Got expected '$expected_result' decision"
        pass_count=$((pass_count + 1))
    else
        echo -e "${RED}❌ FAIL${NC}: Expected '$expected_result', got '$DECISION'"
        fail_count=$((fail_count + 1))
    fi

    echo ""
    echo "Duration: ${DURATION}s"
    echo "Message preview:"
    echo "$MESSAGE" | head -10
}

# ─────────────────────────────────────────────────────────────────
# Test 1: No Promises, No Work
# ─────────────────────────────────────────────────────────────────

test1_setup() {
    export CLAUDE_SESSION_ID="test-session-$$"
    rm -f "$HOME/.claude/completion-state/promises/"*.json 2>/dev/null || true
    # Clear todos
    rm -f "$HOME/.claude/todos/"*.json 2>/dev/null || true
    # Add a continuation todo to pass that check
    mkdir -p "$HOME/.claude/todos"
    cat > "$HOME/.claude/todos/test-$$.json" <<'EOF'
{
  "items": [
    {"description": "Check bd ready for next task", "status": "pending"}
  ]
}
EOF
}

run_test "No Promises, No Work" "approve" "test1_setup"

# ─────────────────────────────────────────────────────────────────
# Test 2: Open Promise Blocks
# ─────────────────────────────────────────────────────────────────

test2_setup() {
    export CLAUDE_SESSION_ID="test-session-$$"
    export CLAUDE_PROJECT_DIR="$PROJECT_ROOT"
    mkdir -p "$PROJECT_ROOT/.claude/completion-state/promises"

    # Create a test promise owned by this session
    PROMISE_ID="promise-test$$"
    cat > "$PROJECT_ROOT/.claude/completion-state/promises/$PROMISE_ID.json" <<EOF
{
  "id": "$PROMISE_ID",
  "summary": "Test promise",
  "ownership": {
    "created_by": "test-session-$$",
    "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "owned_by": "test-session-$$",
    "owned_since": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "status": "in_progress",
  "verification": {
    "verified_at": null,
    "verified_by": null,
    "type": null,
    "proof": null
  }
}
EOF

    # Add continuation todo
    mkdir -p "$HOME/.claude/todos"
    cat > "$HOME/.claude/todos/test-$$.json" <<'EOF'
{
  "items": [
    {"description": "Check bd ready for next task", "status": "pending"}
  ]
}
EOF
}

run_test "Open Promise Blocks" "block" "test2_setup"

# ─────────────────────────────────────────────────────────────────
# Test 3: Todo Continuation Required
# ─────────────────────────────────────────────────────────────────

test3_setup() {
    export CLAUDE_SESSION_ID="test-session-$$"
    rm -f "$HOME/.claude/completion-state/promises/"*.json 2>/dev/null || true
    # Clear todos (no continuation item)
    rm -f "$HOME/.claude/todos/"*.json 2>/dev/null || true
}

run_test "Todo Continuation Required" "block" "test3_setup"

# ─────────────────────────────────────────────────────────────────
# Test 4: Performance Benchmark
# ─────────────────────────────────────────────────────────────────

test4_setup() {
    export CLAUDE_SESSION_ID="test-session-$$"
    rm -f "$HOME/.claude/completion-state/promises/"*.json 2>/dev/null || true
    # Add continuation todo
    mkdir -p "$HOME/.claude/todos"
    cat > "$HOME/.claude/todos/test-$$.json" <<'EOF'
{
  "items": [
    {"description": "Check bd ready for next task", "status": "pending"}
  ]
}
EOF
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4: Performance Benchmark"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

test4_setup

# Run 5 times and average
total_time=0
for i in {1..5}; do
    START=$(date +%s%N)
    echo '{}' | bash "$STOP_GATE" > /dev/null 2>&1
    END=$(date +%s%N)
    TIME_MS=$(( (END - START) / 1000000 ))
    total_time=$((total_time + TIME_MS))
    echo "Run $i: ${TIME_MS}ms"
done

avg_time=$((total_time / 5))
echo ""
echo "Average time: ${avg_time}ms"

if [ $avg_time -lt 1500 ]; then
    echo -e "${GREEN}✅ PASS${NC}: Average time ${avg_time}ms < 1500ms target"
    pass_count=$((pass_count + 1))
else
    echo -e "${RED}❌ FAIL${NC}: Average time ${avg_time}ms >= 1500ms target"
    fail_count=$((fail_count + 1))
fi
test_count=$((test_count + 1))

# ─────────────────────────────────────────────────────────────────
# Cleanup and Summary
# ─────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Total: $test_count"
echo -e "${GREEN}Pass: $pass_count${NC}"
echo -e "${RED}Fail: $fail_count${NC}"

# Cleanup
rm -f "$HOME/.claude/completion-state/promises/promise-test"*.json 2>/dev/null || true
rm -f "$HOME/.claude/todos/test-"*.json 2>/dev/null || true

if [ $fail_count -eq 0 ]; then
    echo -e "\n${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}Some tests failed.${NC}"
    exit 1
fi
