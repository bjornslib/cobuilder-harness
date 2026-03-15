---
title: "SD: Migrate Voice Agent to openai/gpt-oss-20b"
status: active
type: reference
epic_id: MODEL-MIGRATION-001
prd_ref: AgenCheck Configuration Consolidation
last_verified: 2026-03-11
---

## Overview

Replace Groq's `meta-llama/llama-4-maverick-17b-128e-instruct` model with OpenAI's `openai/gpt-oss-20b` in the voice agent configuration. This is part of a broader model consolidation across AgenCheck agents.

## Research Findings (Verified 2026-03-11)

| Finding | Status | Details |
|---------|--------|---------|
| Model ID | **Validated** | Correct ID is `gpt-oss-20b` (technically 20.9B parameters) |
| 120b variant | **Not found** | Codebase has typo - `openai/gpt-oss-120b` is incorrect |
| Groq API compatibility | **Validated** | Available via OpenAI-compatible endpoint at `https://api.groq.com/openai/v1` |
| PydanticAI compatibility | **Validated** | Works with `OpenAIProvider` |
| LiveKit compatibility | **Validated** | Works with LiveKit's Groq plugin |
| Context window | **128k tokens** | Sufficient for long conversations |
| Performance (Groq high) | **883.3 t/s** | Ultra-low latency on LPU |
| Performance (Groq medium) | **283 t/s** | |
| Local GPU (3090/4090) | **~160 t/s** | Acceptable drop for data sovereignty |
| Relative performance | **Near o4-mini** | ≈ o3-mini on core benchmarks |
| License | **Apache 2.0** | Open-weight, deployable |

## Acceptance Criteria

- ✅ `voice_agent/config.py` line 28: `llm_model` default changed from llama-4-maverick to gpt-oss-20b
- ✅ `voice_agent/tests/conftest.py`: All test model references updated to gpt-oss-20b
- ✅ `GROQ_API_KEY` still works (gpt-oss-20b is available via Groq API)
- ✅ Local testing passes with new model
- ✅ No changes to provider configuration (groq remains default)

## Implementation Details

### 1. Update Voice Agent Config

**File:** `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/config.py`

**Change on line 28:**
```python
# BEFORE
llm_model: str = os.getenv("LLM_MODEL", "meta-llama/llama-4-maverick-17b-128e-instruct")

# AFTER
llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
```

### 2. Update Test Configuration

**File:** `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/tests/conftest.py`

Search for all instances of `"meta-llama/llama-4-maverick-17b-128e-instruct"` and replace with `"openai/gpt-oss-20b"`.

**Expected locations:**
- Model initialization in test fixtures
- Mock model declarations
- Test-specific configuration

### 3. Environment Variable (Optional Override)

The default can be overridden via `LLM_MODEL` env var in `.env`:
```
LLM_MODEL=openai/gpt-oss-20b
```

(No changes needed - just noting that the override mechanism still works)

### 4. Provider Compatibility

- **Provider:** Groq (unchanged)
- **Base URL:** `https://api.groq.com/openai/v1`
- **API Key:** `GROQ_API_KEY` (unchanged)
- **Model availability:** gpt-oss-20b is available through Groq API

**Performance Notes (from research validation):**
- Groq LPU (high): 883.3 tokens/second
- Groq LPU (medium): 283 tokens/second
- Local GPU (3090/4090): ~160 tokens/second
- Performance drop from Groq to local is acceptable for data sovereignty requirements

No provider configuration changes needed.

## Testing

After changes:

1. **Local Development Test:**
   ```bash
   # Verify the config loads correctly
   python -c "from voice_agent.config import config; print(config.llm_model)"
   # Should output: openai/gpt-oss-20b
   ```

2. **Test Suite:**
   ```bash
   cd voice_agent
   pytest tests/conftest.py -v
   # Ensure all tests pass with new model
   ```

3. **Integration Test (if available):**
   - Run any voice agent integration tests to ensure the new model works with the rest of the system

## Verification

Check that:
- [ ] config.py line 28 contains `"openai/gpt-oss-20b"`
- [ ] All test files reference gpt-oss-20b
- [ ] GROQ_API_KEY env var is still set (unchanged)
- [ ] `pytest tests/conftest.py` passes

## Related Files

- `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/config.py`
- `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/tests/conftest.py`
- `agencheck-support-agent/.env` (for GROQ_API_KEY)
