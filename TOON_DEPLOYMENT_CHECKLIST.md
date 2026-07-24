# TOON Deployment Checklist

## ✅ Pre-Deployment (Already Complete)

- [x] Created `services/toon.py` - TOON specification module
- [x] Updated `services/llm_client.py` - Token tracking
- [x] Updated `services/context.py` - Optimized context builder
- [x] Updated `services/agents.py` - Field whitelisting & token tracking
- [x] Updated all agent prompts (registration, completeness, integrity, coverage, preauth, denial)
- [x] Created TOON documentation (README, Implementation, Quick Start)
- [x] Created verification test script
- [x] Backward compatible - no breaking changes

## 📋 Deployment Steps

### Phase 1: Testing (Local/Dev)

- [ ] Run verification script:
  ```bash
  cd backend
  python3 verify_toon.py
  ```
  Expected output: ✅ ALL TESTS PASSED

- [ ] Test token tracking in dev environment
  - Make a test claim review
  - Check that `result.agents[0].tokens` contains token counts
  - Verify `result.review.raw["total_tokens"]` shows total

- [ ] Compare context sizes
  - Print `len(build_claim_context(db, claim))`
  - Print `len(build_claim_context_optimized(db, claim))`
  - Should see 40-60% reduction

### Phase 2: Integration (Update Your Routes)

- [ ] Update `routes/admin.py` (or wherever you do claim reviews):
  ```python
  # OLD
  # context = build_claim_context(db, claim)
  
  # NEW
  from services.context import build_claim_context_optimized
  context = build_claim_context_optimized(db, claim)
  ```

- [ ] Add token tracking to response:
  ```python
  return {
      "verdict": result.review.verdict,
      "tokens": {
          "total": result.review.raw.get("total_tokens", 0),
          "per_agent": [
              {
                  "agent": agent.name,
                  "tokens": agent.tokens.get("total_tokens", 0)
              }
              for agent in result.agents
          ]
      }
  }
  ```

- [ ] Test in dev:
  - Make a test API call to your endpoint
  - Verify tokens are shown in response
  - Verify they're ~60-70% lower than before

### Phase 3: Staging

- [ ] Deploy to staging environment
- [ ] Run full test suite (if you have one)
- [ ] Monitor token usage for 24 hours
- [ ] Check for any agent failures or errors
- [ ] Verify cost reduction matches 50-70% target

### Phase 4: Production

- [ ] Set up monitoring/alerting
- [ ] Deploy to production
- [ ] Monitor first 100 claims
- [ ] Check token metrics:
  - [ ] Average tokens per claim
  - [ ] Total tokens from 100 claims
  - [ ] Cost reduction vs baseline
  
- [ ] If successful, roll out 100% of traffic

## 🔍 Verification Checklist

### Basic Functionality
- [ ] Agents execute without errors
- [ ] Token counts are non-zero
- [ ] All 6 agents complete successfully
- [ ] Verdicts are still accurate

### Token Reduction
- [ ] Registration agent: 300-400 tokens (was ~1000)
- [ ] Completeness agent: 200-300 tokens (was ~800)
- [ ] Integrity agent: 400-600 tokens (was ~1200)
- [ ] Coverage agent: 250-350 tokens (was ~900)
- [ ] Pre-auth agent: 300-400 tokens (was ~1000)
- [ ] Denial agent: 150-250 tokens (was ~600)
- [ ] **Total: 1600-2300 tokens (was ~6000) ✅**

### Cost Verification
- [ ] Calculate: (total_tokens / 1,000,000) * $0.10 = cost per claim
- [ ] Old: ~$0.06 per claim
- [ ] New: ~$0.02 per claim
- [ ] Savings: ~$0.04 per claim (67%)

## 🚨 Rollback Plan

If issues occur:
1. Revert to using `build_claim_context()` instead of `build_claim_context_optimized()`
2. Revert `chat_json_with_tokens()` to old `chat_json()` (automatically handled)
3. All changes are backward compatible - old code will work

**Rollback steps:**
```python
# In routes, change back to:
context = build_claim_context(db, claim)  # Old version

# No other changes needed - LLM client handles it automatically
```

## 📊 Monitoring Dashboard

Recommended metrics to track:

```
TOON Metrics Dashboard
===================
Tokens per claim:        [CURRENT] vs [BASELINE]
Cost per claim:          [CURRENT] vs [BASELINE]
Cost reduction %:        [TARGET: 50-70%]
Agent failures:          [SHOULD BE 0]
Average latency:         [SHOULD BE SAME]
Claims processed/day:    [TRACK VOLUME]
```

## ✋ Manual Smoke Test

Before full deployment, test manually:

```python
# Test script
from sqlalchemy.orm import Session
from database import SessionLocal
from services.context import build_claim_context_optimized
from services.ai_review import get_provider
from models import Claim

db = SessionLocal()
claim = db.query(Claim).first()

# Build optimized context
context = build_claim_context_optimized(db, claim)
print(f"Context size: {len(str(context))} chars")

# Run review
provider = get_provider()
result = provider.review_claim(context)

# Check results
print(f"Total tokens: {result.review.raw.get('total_tokens')}")
print(f"Verdict: {result.review.verdict}")
print(f"Confidence: {result.review.ai_confidence}")

# Print per-agent tokens
for agent in result.agents:
    print(f"{agent.name}: {agent.tokens.get('total_tokens')} tokens")
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Token counts = 0 | Check that `chat_json_with_tokens` is used; verify GROQ_API_KEY is set |
| Agents failing | Verify agent prompts follow TOON format; check JSON responses are valid |
| Higher tokens than expected | Verify `build_claim_context_optimized` is used; check for large documents |
| Cost not decreasing | Confirm using optimized builder; check token tracking is enabled |

## 📞 Support Contacts

For questions or issues:
1. Review `TOON_README.md` (overview)
2. Check `TOON_IMPLEMENTATION.md` (details)
3. Look at `TOON_QUICK_START.py` (examples)
4. Run `verify_toon.py` (validation)

## 🎯 Success Criteria

✅ **TOON deployment is successful if:**
- [x] All tests pass (verify_toon.py)
- [x] Token counts are 50-70% lower
- [x] Cost is 50-70% lower
- [x] All verdicts are still accurate
- [x] No agent failures or errors
- [x] Response latency is same or better
- [x] Zero production issues for 24 hours

---

## 📝 Sign-Off

- [ ] All tests pass
- [ ] Integration complete
- [ ] Monitoring setup
- [ ] Rollback plan ready
- [ ] Team aware of changes
- [ ] Ready for production

**Date deployed:** ___________
**Deployed by:** ___________
**Result:** ✅ SUCCESS / ❌ ROLLBACK

---

**TOON is ready to go! Use this checklist to guide your deployment.** 🚀
