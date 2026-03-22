---
title: "Validation"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Validation & Testing

Testing infrastructure and troubleshooting for orchestrator sessions.

**Part of**: [Multi-Agent Orchestrator Skill](SKILL.md)

**When to use this guide:**
- Setting up testing infrastructure
- Running validation at any level (Unit, API, E2E)
- Service startup and health checks
- Troubleshooting test failures or service issues
- Recovery from worker or orchestrator failures

---

## Table of Contents

1. [3-Level Validation Protocol](#3-level-validation-protocol)
2. [Service Management](#service-management)
3. [Testing Infrastructure](#testing-infrastructure)
4. [Troubleshooting](#troubleshooting)
5. [Recovery Patterns](#recovery-patterns)

---

## 3-Level Validation Protocol

**Every feature must pass all three levels before closure.**

**Orchestrator Validation Scope: Level 1 Only**

Orchestrators run Level 1 validation (unit tests, basic smoke tests) before marking tasks `impl_complete`.
Level 2 (API tests) and Level 3 (E2E browser tests) are performed independently by System 3's oversight team.

The orchestrator does NOT invoke validation-test-agent, acceptance-test-runner, or acceptance-test-writer.

### Level 1: Unit Tests

```bash
# Backend (Python)
cd my-project-backend && pytest tests/ -v --tb=short

# Frontend (TypeScript)
cd my-project-frontend && npm run test
```

**Component Test Pattern (Frontend)**:
```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInterface } from '@/components/ChatInterface';

describe('ChatInterface', () => {
  it('should display message input', () => {
    render(<ChatInterface />);
    expect(screen.getByPlaceholderText(/type.*message/i)).toBeInTheDocument();
  });
});
```

### Level 2: API Tests

```bash
# Health checks for all services
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:5184/health | jq .
curl -s http://localhost:5185/health | jq .

# Main endpoint test
curl -X POST http://localhost:8000/my-project \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Can MIT credentials be verified?",
    "thread_id": "test-session-001",
    "include_citations": true
  }'
```

**Expected Response Structure**:
```json
{
  "response": "MIT offers credential verification through...",
  "citations": [...],
  "confidence": 0.85,
  "tool_used": "verify_education"
}
```

### Level 3: E2E Browser Tests

**Primary approach**: Structured Markdown specifications executed via chrome-devtools MCP tools.

#### Chrome Health Check (MANDATORY before Level 3)

Before executing any browser tests, verify Chrome connectivity:

```bash
# Quick check: can Claude in Chrome tools respond?
# Use mcp__claude-in-chrome__tabs_context_mcp to verify extension connection
```

**Decision tree:**
- Chrome connected --> Proceed with Level 3
- Chrome disconnected --> Skip Level 3, flag tests as INCOMPLETE in report
- Chrome disconnects mid-session --> Fail gracefully, mark remaining tests as INCOMPLETE

#### Complete Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. TEST SPECIFICATION (Markdown)                                    │
│    Location: my-project-frontend/__tests__/e2e/specs/       │
│    Template: TEMPLATE.md                                            │
│    Format: Given/When/Then with MCP chrome-devtools steps          │
└──────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. WORKER EXECUTION (via native teammate or Task subagent)          │
│    - Orchestrator delegates to Worker teammate via TaskCreate      │
│    - Worker reads the test spec Markdown file                      │
│    - Worker executes tests using chrome-devtools MCP tools         │
│    - Worker captures screenshots as evidence                       │
└──────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. EXECUTION REPORT (Markdown)                                      │
│    Location: __tests__/e2e/results/J{N}/J{N}_EXECUTION_REPORT.md   │
│    Template: EXECUTION_REPORT_TEMPLATE.md                           │
│    Contents: Pass/Fail per test, evidence manifest, issues found   │
└──────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. ORCHESTRATOR REVIEW                                              │
│    - Reviews execution report for anomalies                        │
│    - Sense-checks results against expected behavior                │
│    - Re-executes any tests that seem incorrect                     │
│    - Approves or requests fixes                                    │
└──────────────────────────────────────────────────────────────────────┘
```

#### Key Files

| File | Purpose |
|------|---------|
| `__tests__/e2e/specs/TEMPLATE.md` | Standard format for test specifications |
| `__tests__/e2e/specs/J{N}-*.md` | Journey-specific test specs (J1-J10) |
| `__tests__/e2e/results/EXECUTION_REPORT_TEMPLATE.md` | Standard format for execution reports |
| `__tests__/e2e/results/J{N}/J{N}_EXECUTION_REPORT.md` | Filled-out execution report per journey |
| `__tests__/e2e/results/J{N}/*.png` | Screenshot evidence |

#### Test Spec Execution Workflow

1. **Discover specs**: Read `docs/tests/specs/*.md` for available test specifications
2. **Filter by service**: Match specs to the feature being validated (frontmatter `service` field)
3. **Delegate execution**: Pass spec markdown to validation agent with Claude in Chrome access
4. **Agent follows steps literally**: Each numbered step is executed using Chrome DevTools MCP tools
5. **Capture evidence**: Screenshots and page content captured per the spec's Evidence section
6. **Write report**: Results written to `docs/tests/reports/{date}-{spec-id}.md`

See `docs/tests/TEST_SPEC_FORMAT.md` for the canonical test specification format.

#### Test Reports

Reports are written to `docs/tests/reports/` with naming convention:
`{YYYY-MM-DD}-{spec-id}.md`

**Report Template:**
```markdown
---
title: "Test Report: {spec title}"
spec: "{spec-id}"
date: "{YYYY-MM-DD}"
status: pass|fail|incomplete
agent: "{agent-id}"
---

## Results

| Step | Action | Expected | Actual | Status |
|------|--------|----------|--------|--------|
| 1 | Navigate to ... | Page loads | Page loaded in 2.3s | PASS |
| 2 | Fill input with ... | Text appears | Text entered | PASS |

## Evidence

| Screenshot | Step | Description |
|-----------|------|-------------|
| `screenshots/01-*.png` | 1 | Initial page state |

## Summary

- Total steps: X
- Passed: Y
- Failed: Z
- Incomplete: W
- Overall: PASS/FAIL/INCOMPLETE
```

#### Browser Testing Commands

```javascript
// Basic Navigation
await navigate_page({url: "http://localhost:5001"});
await take_snapshot();  // Capture accessibility tree

// Chat Interaction
await fill({
  uid: "[input-uid-from-snapshot]",
  value: "Can you verify MIT credentials?"
});
await click({ uid: "[button-uid-from-snapshot]" });
await wait_for({ text: "response text" });
await take_snapshot();
```

**Visual Validation Points**:
- Chat messages render correctly
- Loading states display properly
- Error messages are visible and clear
- Session list updates in real-time
- No white-on-white text issues

#### Epic Closure Gate

**Epic Closure Gate**: At least one browser test spec must PASS for epic closure. If all browser tests are INCOMPLETE (Chrome unavailable), epic closure is permitted but flagged.

---

## Service Management

### Service Ports

| Port | Service | Purpose |
|------|---------|---------|
| 5001 | Frontend (Next.js) | React UI dev server |
| 8000 | Backend (FastAPI) | Main API server |
| 5184 | eddy_validate (MCP) | Education verification service |
| 5185 | user_chat (MCP) | Knowledge base service |
| 5186 | university-contact-manager | Contact management |
| 8001 | eddy_deep_research | Deep research agent |

### Architecture Flow

```
User Request → Frontend (5001) → Backend Orchestrator (8000) →
    Aura Graph (enhanced_aura_orchestrator.py) →
        → eddy_validate MCP (5184) → verify_education tool
        → user_chat MCP (5185) → search_knowledge_base tool
    → Structured JSON Response → Frontend
```

### Starting Services

**Backend Services**:
```bash
cd $CLAUDE_PROJECT_DIR/my-project-backend
./start_services.sh
```

**Startup Sequence** (order matters for dependencies):
1. eddy_validate MCP (5184) - Must start first
2. user_chat MCP (5185) - Depends on knowledge base
3. university-contact-manager (5186) - Contact data service
4. eddy_deep_research (8001) - Deep research capabilities
5. Main backend (8000) - Requires all MCP services

**Frontend**:
```bash
cd $CLAUDE_PROJECT_DIR/my-project-frontend
npm run dev
# Starts on port 5001 with Turbopack
```

### Health Checks

**One-Liner Health Check**:
```bash
for port in 8000 5184 5185 5186 8001; do
  echo "Port $port: $(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health)"
done
```

**Pre-Flight Checklist**:
```bash
# 1. Services exist
[ "$(tmux list-sessions | grep -c -E 'frontend|backend')" -eq 2 ] && \
  echo "✅ Services running" || echo "❌ Start services first"

# 2. Ports listening
[ "$(lsof -i :5001 -i :8000 | grep -c LISTEN)" -ge 2 ] && \
  echo "✅ Ports active" || echo "❌ Services not responding"

# 3. Backend health
curl -s http://localhost:8000/health | grep -q "healthy" && \
  echo "✅ Backend healthy" || echo "❌ Backend not responding"
```

### Starting from Clean State

Use when services crashed, port conflicts detected, or after system reboot:

```bash
# Step 1: Kill any processes on service ports
lsof -i :5001 -i :8000 -i :5184 -i :5185 | \
  grep -v "^COMMAND" | awk '{print $2}' | sort -u | xargs -r kill -9

# Step 2: Kill old tmux sessions
tmux kill-session -t frontend 2>/dev/null || true
tmux kill-session -t backend 2>/dev/null || true

# Step 3: Verify ports are free
sleep 2
lsof -i :5001 -i :8000 -i :5184 -i :5185 | grep LISTEN && \
  echo "❌ Ports still in use" || echo "✅ Ports free"

# Step 4: Start backend services
cd $CLAUDE_PROJECT_DIR/my-project-backend
tmux new-session -d -s backend -c "$(pwd)"
tmux send-keys -t backend "./start_services.sh"
tmux send-keys -t backend Enter
sleep 10

# Step 5: Start frontend
cd $CLAUDE_PROJECT_DIR/my-project-frontend
tmux new-session -d -s frontend -c "$(pwd)"
tmux send-keys -t frontend "npm run dev"
tmux send-keys -t frontend Enter
sleep 15

# Step 6: Final health check
curl -s http://localhost:8000/health && echo "✅ Backend healthy"
curl -s http://localhost:5001 | head -5 && echo "✅ Frontend responding"
```

---

## Testing Infrastructure

### Testing Matrix

| Feature Type | Unit Test | API Test | Browser Test |
|--------------|-----------|----------|--------------|
| Pure function logic | ✅ | ❌ | ❌ |
| API endpoint | ✅ | ✅ | ❌ |
| React component render | ✅ | ❌ | ✅ |
| User workflow | ❌ | ❌ | ✅ |
| Visual styling | ❌ | ❌ | ✅ |
| MCP tool integration | ✅ | ✅ | ❌ |
| Cross-service flow | ❌ | ✅ | ✅ |

### Key Backend Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, /my-project endpoint |
| `enhanced_aura_orchestrator.py` | Core orchestration logic |
| `aura/aura_graph_v2.py` | Response-first graph |
| `aura/aura_prompt.py` | Prompt generation |
| `dependencies.py` | Model config and DI |
| `utils/history_manager.py` | Conversation persistence |

### Key Frontend Files

| File | Purpose |
|------|---------|
| `/app/page.tsx` | Main chat page entry |
| `/components/ChatInterface.tsx` | Primary chat component |
| `/stores/slices/threadSlice.ts` | Zustand thread state |
| `/stores/slices/messageSlice.ts` | Zustand message state |
| `/playwright.config.ts` | E2E test configuration |

### MCP Service Testing

**eddy_validate MCP (Port 5184)**:
```bash
curl -X POST http://localhost:5184/verify \
  -H "Content-Type: application/json" \
  -d '{"institution": "MIT", "credential_type": "degree"}'
```

**user_chat MCP (Port 5185)**:
```bash
curl -X POST http://localhost:5185/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I verify credentials?", "top_k": 5}'
```

---

## Troubleshooting

### The Hollow Test Problem

**Critical Learning:** Tests can pass while the actual feature doesn't work.

**What Are Hollow Tests?** Unit/integration tests that use mocks returning expected values, creating false confidence.

**Example**:
```python
# Test that passes but feature doesn't work
def test_login_endpoint(mock_auth):
    mock_auth.return_value = {"token": "abc123"}  # Mock always succeeds
    response = client.post("/api/auth", json={"email": "test@example.com"})
    assert response.status_code == 200  # ✅ Test passes
```

**Reality:** Backend `/api/auth` endpoint doesn't exist, returns 404 in production.

**Hierarchy of Test Confidence**:

| Test Type | Confidence Level | What It Misses |
|-----------|------------------|----------------|
| Unit tests | 🔴 Low | Integration, real API calls |
| Integration tests | 🟡 Medium | Backend availability, network |
| E2E browser tests | 🟢 High | - |
| Manual API testing | 🟢 High | Frontend integration |

**Prevention**: Always run Explore validation after tests pass:
```
Task(subagent_type="Explore", prompt="Validate <bd-id> works as designed:
- Test actual user workflow (not mocked)
- Verify API endpoints return real data
- Check UI displays expected results")
```

### Worker Red Flags

| Red Flag | Meaning | Action |
|----------|---------|--------|
| Modified files outside scope | Worker didn't follow constraints | **Reject** - Fresh retry with scope reminder |
| TODO/FIXME in output | Worker left incomplete work | **Reject** - Fresh retry, demand complete code |
| Validation steps fail | Feature doesn't actually work | **Reject** - Fresh retry or decompose further |
| Uncommitted changes | Worker didn't follow protocol | **Reject** - Complete commit first |
| "I think" / "probably" in response | Worker is guessing, not verifying | **Review carefully** - Demand verification |
| Worker exceeds 2 hours | Feature not sized correctly | **Stop** - Re-decompose feature |
| Worker spawns 10+ sub-agents | Feature too complex | **Stop** - Split into multiple features |
| Generic error handling (`except: pass`) | Low-quality code | **Reject** - Demand proper error handling |
| Hardcoded values (API keys, URLs) | Bad practices | **Reject** - Use environment variables |

**Key Insight: Reject vs. Fix**

Don't try to fix bad worker output:
- ❌ "Please modify your code to..."
- ❌ "Can you update the file to include..."

Instead, reject and retry fresh:
- ✅ Kill worker session
- ✅ Create new worker session
- ✅ Provide clearer constraints
- ✅ Fresh reasoning chain, better result

### Orchestrator Anti-Patterns

| Anti-Pattern | Why It's Bad | Correct Approach |
|--------------|--------------|------------------|
| Starting multiple features simultaneously | Confuses state, impossible to isolate failures | **One feature at a time** |
| Skipping regression check | Hidden regressions accumulate | **Always check 1-2 passed features first** |
| Marking features passing without validation | Hollow success, tech debt | **Run validation steps, verify output** |
| Allowing workers to exceed scope | Code sprawl, unexpected side effects | **Reject and retry with tighter scope** |
| Continuing after regression failure | Building on broken foundation | **Stop, fix regression, then proceed** |
| Not documenting blockers | Next session wastes time rediscovering | **Update summary with blockers** |

### Service Issues

| Issue | Quick Fix |
|-------|-----------|
| Port already in use | `lsof -i :5001 \| awk 'NR>1 {print $2}' \| xargs kill -9` |
| Backend won't start | Check logs: `tmux capture-pane -t backend -p \| grep -i error` |
| Frontend won't compile | `cd frontend && npm install && npm run dev` |
| Services running but tests fail | Add `sleep 5` before tests (race condition) |

**Common Backend Startup Failures**:
- Missing Python dependencies → `pip install -r requirements.txt`
- Wrong Python version → Verify Python 3.11+
- Database not accessible → Check Supabase connection
- Environment variables missing → Check `.env` file

**Common Frontend Startup Failures**:
- Missing node_modules → `npm install`
- Wrong Node version → Verify Node 18+
- TypeScript errors → Check for build errors in logs
- Port 5001 already in use → Kill existing process

### Voting Protocol

**When to use voting consensus:**

| Scenario | Use Voting? |
|----------|-------------|
| Architecture decision with multiple valid approaches | ✅ Yes |
| Critical path feature (errors are costly) | ✅ Yes |
| After 2+ failed attempts on same feature | ✅ Yes |
| Straightforward implementation | ❌ No |
| Single obvious solution | ❌ No |

**Process**:
1. Define voting question clearly
2. Launch 3-5 workers with identical context
3. Each worker produces solution independently
4. Collect and analyze for consensus
5. **Strong consensus** (4/5): Implement it
6. **Weak consensus** (3/5): Review carefully, likely implement
7. **No consensus**: Problem needs decomposition

---

## Recovery Patterns

### Pattern 1: Worker Exceeded Scope

**Symptoms:** Files outside scope modified

**Recovery:**
```bash
# 1. Revert changes
git reset --hard HEAD

# 2. Refine scope (make more restrictive)

# 3. Launch fresh worker with explicit scope constraint:
# Task(subagent_type="...", prompt="CRITICAL: ONLY modify these files: [list]. If you need to modify others, report BLOCKED.")
```

**Note:** Native teammates persist across tasks — shut them down via `SendMessage(type="shutdown_request")` when done. Task subagent fallback cleans up automatically.

### Pattern 2: Feature Too Complex

**Symptoms:** Worker spawns 10+ sub-agents, exceeds 2 hours, or fails 2+ times

**Recovery:**
```bash
# 1. Return to decomposition
# Use MAKER checklist in WORKFLOWS.md

# 2. Split F00X into F00X-part1, F00X-part2, F00X-part3

# 3. Proceed with F00X-part1 (should complete in <1 hour now)
```

**Note:** Native teammates persist — use `SendMessage(type="shutdown_request")` for cleanup. Task subagent fallback cleans up automatically when complete or failed.

### Pattern 3: Flaky Tests

**Symptoms:** Feature sometimes passes, sometimes fails (same code)

**Recovery:**
```bash
# 1. Run validation 3 times, observe pattern

# 2. Common fixes:
# - Add explicit waits (browser.waitFor...)
# - Increase timeouts (from 5s to 10s)
# - Add test isolation (clean state between tests)
# - Remove external dependencies (mock external APIs)

# 3. Verify fix: Run test 10 times, should pass all 10
```

### Pattern 4: Hollow Tests Discovered

**Symptoms:** Tests pass, Explore agent reports feature doesn't work

**Recovery:**
```bash
# 1. Mark feature as passes: false

# 2. Identify what's missing (endpoint? integration? data?)

# 3. Create remediation feature

# 4. Implement remediation

# 5. Re-validate with Explore agent

# 6. Add E2E test to prevent future hollow tests
```

### Pattern 5: Regression Check Failure

**Symptoms:** Previously passing features now fail

**Immediate Response:**
```bash
# 1. STOP all new work immediately

# 2. Identify what changed
git log --oneline -10
git diff <old-commit>..HEAD

# 3. Determine cause:
# - Recent feature broke it? → Revert and re-implement with better isolation
# - Environment changed? → Check services, database, ports
# - Test was flaky? → Fix flaky test first
```

---

## Related Documents

- **[SKILL.md](SKILL.md)** - Main orchestrator skill entry point
- **[WORKFLOWS.md](WORKFLOWS.md)** - 4-Phase Pattern, Autonomous Mode, Validation Protocol
- **[WORKERS.md](WORKERS.md)** - Worker delegation patterns
- **Beads** - Task management (use `bd` commands directly)
- **[PREFLIGHT.md](PREFLIGHT.md)** - Session start checklist

---

**Document Version**: 1.1
**Last Updated**: 2026-02-17
**Consolidated From**: TESTING_INFRASTRUCTURE.md, TROUBLESHOOTING.md, SERVICE_MANAGEMENT.md

**Changelog**:
- **1.1** (2026-02-17): Enhanced Level 3 E2E Browser Tests section for F3.2 (Browser Validation Integration). Added Chrome Health Check gate, Test Spec Execution Workflow referencing `docs/tests/TEST_SPEC_FORMAT.md`, Test Reports output format with `docs/tests/reports/` convention, and Epic Closure Gate rule.
- **1.0** (2026-01-07): Initial consolidated document.
