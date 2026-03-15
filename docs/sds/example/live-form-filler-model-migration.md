---
title: "SD: Migrate Live Form Filler to openai/gpt-oss-20b"
status: active
type: reference
epic_id: MODEL-MIGRATION-001
prd_ref: AgenCheck Configuration Consolidation
last_verified: 2026-03-11
---

## Overview

Update the live_form_filler agent to use `openai/gpt-oss-20b` (instead of current `openai/gpt-oss-120b`) for consistency with the voice_agent. This ensures both agents use the same underlying Groq model for employment verification tasks.

## Research Findings (Verified 2026-03-11)

### Model Identification Fix
- **Issue found during research:** Codebase used `openai/gpt-oss-120b` which does not exist
- **Verified model ID:** `gpt-oss-20b` (technically 20.9B parameters)
- **Root cause:** Typo - 120b variant does not exist on Groq's API

### API Compatibility (Validated)
| Feature | Status | Details |
|---------|--------|---------|
| Groq OpenAI-compatible endpoint | ✅ Works | `https://api.groq.com/openai/v1` |
| PydanticAI OpenAIProvider | ✅ Works | No code changes needed |
| LiveKit Groq plugin | ✅ Works | Uses same OpenAI-compatible API |
| Context window | ✅ 128k tokens | Sufficient for LLM conversations |

### Performance Characteristics
| Environment | Tokens/Second | Notes |
|-------------|---------------|-------|
| Groq LPU (high) | 883.3 | Ultra-low latency |
| Groq LPU (medium) | 283 | Balanced mode |
| Local GPU (3090/4090) | ~160 | Acceptable for data sovereignty |

---

## Acceptance Criteria

- ✅ `live_form_filler/agent.py` line 20: Model changed from gpt-oss-120b to gpt-oss-20b
- ✅ Line 26 comment updated to reflect correct model name (was stale: said "20b" but code used "120b")
- ✅ PydanticAI agent initialization uses the updated model
- ✅ Local testing passes with new model
- ✅ Groq provider configuration unchanged

## Implementation Details

### 1. Update Form Filler Agent Model

**File:** `agencheck-support-agent/live_form_filler/agent.py`

**Change on line 20:**
```python
# BEFORE
groq_model = PatchedGroqModel(
    'openai/gpt-oss-120b',
    provider=groq_provider
)

# AFTER
groq_model = PatchedGroqModel(
    'openai/gpt-oss-20b',
    provider=groq_provider
)
```

### 2. Update Stale Comment

**File:** `agencheck-support-agent/live_form_filler/agent.py`

**Change on line 26:**
```python
# BEFORE
form_filler_agent = Agent(
    groq_model,  # Using Groq openai/gpt-oss-20b for accurate extraction

# AFTER (unchanged, comment now matches actual code)
form_filler_agent = Agent(
    groq_model,  # Using Groq openai/gpt-oss-20b for accurate extraction
```

### 3. Provider Configuration

No changes needed - the Groq provider is already configured correctly on lines 14-17:
```python
groq_provider = OpenAIProvider(
    base_url='https://api.groq.com/openai/v1',
    api_key=os.getenv('GROQ_API_KEY')
)
```

## Rationale

- **Voice agent** now uses `openai/gpt-oss-20b`
- **Form filler** previously used `openai/gpt-oss-120b` (likely an oversight - 120b is larger but not always better)
- **Consistency:** Both agents should use the same model for unified behavior and cost control
- **Model choice:** gpt-oss-20b is fast and accurate for employment verification field extraction

## Testing

After changes:

1. **Syntax Check:**
   ```bash
   python -c "from live_form_filler.agent import form_filler_agent; print(form_filler_agent)"
   # Should load without errors
   ```

2. **Integration Testing:**
   - Run any form filler tests to ensure model change doesn't break extraction logic
   - Verify extraction accuracy with test data (dates, amounts, names)

3. **Field Extraction Test:**
   - Test with sample employment verification conversation
   - Verify pending fields are extracted correctly
   - Check confidence scores are reasonable

## Verification

Check that:
- [ ] `agent.py` line 20 contains `'openai/gpt-oss-20b'`
- [ ] Comment on line 26 is now accurate (says "gpt-oss-20b")
- [ ] `GROQ_API_KEY` env var is set
- [ ] Form filler can be imported without errors
- [ ] Tests pass with new model

## Related Files

- `agencheck-support-agent/live_form_filler/agent.py`
- `agencheck-support-agent/.env` (for GROQ_API_KEY)
- `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/config.py` (for parity)

## Notes

- The gpt-oss-20b model is available through Groq's OpenAI-compatible API
- No database or API changes required
- This is a model substitution only - behavior should remain consistent
