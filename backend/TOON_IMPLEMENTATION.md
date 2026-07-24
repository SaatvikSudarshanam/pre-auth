# TOON: Token Object Optimization Notation

**Comprehensive token reduction system for the pre-auth pipeline**

## What is TOON?

TOON is a multi-layer token optimization strategy implemented across:
1. **Compact JSON schemas** - Field abbreviations, null removal
2. **Field whitelisting** - Agent-specific context (not all fields for all agents)
3. **Response templating** - Compact response formats
4. **Hierarchical summarization** - Progressive detail (summaries vs full text)
5. **Token tracking** - Per-agent token budgeting
6. **Progressive summarization** - Truncated documents, key-only rules

## Token Savings Breakdown

### 1. Field Abbreviation (~20-30% savings)
**Before:**
```json
{
  "claim_id": 123,
  "claim_type": "procedure",
  "provider_name": "Dr. Smith",
  "diagnosis_text": "Appendicitis"
}
```

**After (TOON):**
```json
{
  "cid": 123,
  "ct": "procedure",
  "pn": "Dr. Smith",
  "dx": "Appendicitis"
}
```

### 2. Field Whitelisting (~40-60% savings)
Each agent only receives relevant fields:

- **Registration Agent**: claim basics + identity
- **Completeness Agent**: claim ID + document list
- **Integrity Agent**: documents only
- **Coverage Agent**: claim amount + plan rules
- **Pre-Auth Agent**: all upstream findings
- **Denial Agent**: verdict + findings only

### 3. Null Removal (~5-10% savings)
```json
// BEFORE
{"field1": "value", "field2": null, "field3": ""}

// AFTER (TOON)
{"field1": "value"}
```

### 4. Document Truncation (~30-50% savings)
- **Full documents**: Passed only to Integrity Agent
- **Truncated (1000 chars)**: Registration, Completeness agents
- **Summary only**: Coverage, Pre-Auth agents

### 5. Compact JSON (~5-10% savings)
```json
// BEFORE
{
  "field": "value",
  "array": [1, 2, 3]
}

// AFTER (TOON)
{"field":"value","array":[1,2,3]}
```

## Total Expected Savings: **50-70% per request**

Example: 6 agents × 1000 tokens each = 6000 tokens/request
With TOON: 6 agents × 300-500 tokens each = 1800-3000 tokens/request

## Implementation Files

### Core Modules
- **`services/toon.py`** - TOON specification, abbreviations, whitelisting
- **`services/llm_client.py`** - Token tracking (chat_json_with_tokens)
- **`services/context.py`** - Optimized context builder (build_claim_context_optimized)
- **`services/agents.py`** - Agent pipeline with TOON field whitelisting
- **`prompts/TOON_GUIDELINES.txt`** - Guidelines for all agents

### Updated Prompts
- **`prompts/agents/registration.txt`** - TOON-optimized registration agent

## How to Use

### 1. In your route handler (e.g., `routes/admin.py`):
```python
from services.context import build_claim_context_optimized
from services.ai_review import get_provider

# Build optimized context
context = build_claim_context_optimized(db, claim)

# Run pipeline (automatically uses TOON)
provider = get_provider()
result = provider.review_claim(context)

# Access token usage
for agent in result.agents:
    print(f"{agent.name}: {agent.tokens['total_tokens']} tokens")
print(f"Total: {result.review.raw['total_tokens']} tokens")
```

### 2. Update remaining agent prompts:
All prompts should follow the `prompts/TOON_GUIDELINES.txt`:
- Use abbreviated field names
- Return compact JSON only
- Keep descriptions under 100 chars
- Reference upstream findings by key

### 3. Monitor token usage:
```python
# Track budgets per agent
from services.toon import TokenBudget

budget = TokenBudget(budget_per_agent=500)  # Hard limit per agent
for agent in result.agents:
    budget.record(agent.key, agent.tokens["prompt_tokens"], agent.tokens["completion_tokens"])

report = budget.report()
print(f"Total tokens: {report['total_tokens']}")
print(f"Over budget: {report['agents_over_budget']}")
```

## TOON Field Abbreviations

| Long Form | TOON | | Long Form | TOON |
|-----------|------|---|-----------|------|
| claim_id | cid | | plan_name | pln |
| claim_type | ct | | annual_limit | lim |
| amount | amt | | deductible | ded |
| provider_name | pn | | copay_percent | copay |
| date_of_service | dos | | member_id | mid |
| diagnosis_text | dx | | full_name | nm |
| status | st | | email | em |
| doc_type | dt | | verdict | verd |
| filename | fn | | confidence | conf |
| summary | sum | | message | msg |
| issues | iss | | identity_match | id_match |

## Migration Checklist

- [x] Create TOON specification (`services/toon.py`)
- [x] Add token tracking to LLM client
- [x] Create optimized context builder
- [x] Update agent pipeline with whitelisting
- [x] Update registration prompt (example)
- [ ] Update remaining agent prompts (completeness, integrity, coverage, pre_auth, denial)
- [ ] Update admin routes to use optimized context
- [ ] Add token reporting to admin dashboard
- [ ] Monitor real-world token reduction

## Expected Results

**Before TOON:**
- ~6000 tokens per claim review
- $0.06 per request (at Groq's ~$0.10/M tokens)

**After TOON:**
- ~2000-3000 tokens per claim review
- $0.02-0.03 per request
- **50-70% cost reduction**

## Troubleshooting

### "Field not found in whitelisted context"
- Check `AGENT_CONTEXT_FIELDS` in `services/toon.py`
- Ensure agent-specific context includes required fields

### Agents returning incomplete data
- Verify agent prompts follow TOON_GUIDELINES.txt
- Check that compact JSON parsing is working (test with `compact_deserialize`)

### Token counts lower than expected
- Verify `chat_json_with_tokens` is being called (not legacy `chat_json`)
- Check Groq API response includes `usage` field

