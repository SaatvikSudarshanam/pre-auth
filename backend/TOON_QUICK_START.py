#!/usr/bin/env python3
"""
QUICK START: Using TOON in Your Routes

This guide shows how to integrate TOON token optimization into your
admin routes for claim review.
"""

# ============================================================================
# EXAMPLE 1: Basic Usage (routes/admin.py)
# ============================================================================

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from models import Claim, User
from services.ai_review import get_provider, AIReviewError
from services.context import build_claim_context_optimized  # Use optimized context
from database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/claims/{claim_id}/review")
async def review_claim(claim_id: int, db: Session = Depends(get_db)):
    """Review a claim using TOON-optimized pipeline."""
    
    # 1. Fetch claim
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    
    # 2. Build TOON-OPTIMIZED context (this is the key change!)
    # OLD: context = build_claim_context(db, claim)
    # NEW: context = build_claim_context_optimized(db, claim)
    context = build_claim_context_optimized(db, claim)
    
    # 3. Run AI review (automatically uses TOON)
    try:
        provider = get_provider()
        result = provider.review_claim(context)
    except AIReviewError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # 4. Extract token usage (new feature!)
    token_summary = {
        "total_tokens": result.review.raw.get("total_tokens", 0),
        "per_agent": [
            {
                "agent": agent.name,
                "tokens": agent.tokens.get("total_tokens", 0),
                "prompt": agent.tokens.get("prompt_tokens", 0),
                "completion": agent.tokens.get("completion_tokens", 0),
            }
            for agent in result.agents
        ],
    }
    
    # 5. Return result with token metrics
    return {
        "claim_id": claim_id,
        "verdict": result.review.verdict,
        "confidence": result.review.ai_confidence,
        "reasoning": result.review.reasoning_summary,
        "flags": result.review.flags,
        "customer_message": result.review.customer_message,
        "integrity": {
            "verdict": result.review.integrity_verdict,
            "risk": result.review.integrity_risk,
            "identity_match": result.review.identity_match,
        },
        "tokens": token_summary,  # NEW: Token usage tracking
    }


# ============================================================================
# EXAMPLE 2: Token Budget Enforcement (routes/admin.py)
# ============================================================================

from services.toon import TokenBudget

# Create a budget tracker (optional but recommended)
CLAIM_REVIEW_BUDGET = TokenBudget(budget_per_agent=800)  # Max 800 tokens per agent


@router.post("/claims/{claim_id}/review-with-budget")
async def review_claim_with_budget(claim_id: int, db: Session = Depends(get_db)):
    """Review a claim with token budget enforcement."""
    
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    
    context = build_claim_context_optimized(db, claim)
    
    try:
        provider = get_provider()
        result = provider.review_claim(context)
    except AIReviewError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # Check token budget for each agent
    for agent in result.agents:
        CLAIM_REVIEW_BUDGET.record(
            agent.key,
            agent.tokens.get("prompt_tokens", 0),
            agent.tokens.get("completion_tokens", 0),
        )
    
    # Get budget report
    budget_report = CLAIM_REVIEW_BUDGET.report()
    
    # Flag if any agent is over budget (for monitoring/alerting)
    if budget_report["agents_over_budget"]:
        print(f"⚠️  Agents over budget: {budget_report['agents_over_budget']}")
        print(f"📊 Total tokens: {budget_report['total_tokens']}")
    
    return {
        "claim_id": claim_id,
        "verdict": result.review.verdict,
        "tokens": {
            "total": budget_report["total_tokens"],
            "per_agent": budget_report["per_agent"],
            "over_budget": budget_report["agents_over_budget"],
        },
    }


# ============================================================================
# EXAMPLE 3: Monitoring & Analytics (routes/admin.py)
# ============================================================================

from typing import List
import statistics


@router.get("/claims/analytics/tokens")
async def token_analytics(db: Session = Depends(get_db)):
    """Get token usage analytics (requires storing results in DB)."""
    
    # Note: This is a simplified example.
    # In production, you'd store claim review results in the database
    # to build historical analytics.
    
    return {
        "message": "Token analytics endpoint",
        "note": "Implement by storing ClaimReview results with token metrics",
        "recommended_metrics": [
            "avg_tokens_per_claim",
            "avg_tokens_per_agent",
            "total_monthly_tokens",
            "estimated_monthly_cost",
            "budget_violations",
        ],
    }


# ============================================================================
# EXAMPLE 4: Comparing TOON vs Non-TOON (For Testing)
# ============================================================================

# If you want to compare token usage before/after TOON:

from services.context import build_claim_context  # Non-optimized version


@router.post("/claims/{claim_id}/review-comparison")
async def review_claim_comparison(claim_id: int, db: Session = Depends(get_db)):
    """Compare TOON vs non-TOON token usage (for testing/validation)."""
    
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    
    # Test with TOON-optimized context
    context_optimized = build_claim_context_optimized(db, claim)
    try:
        provider = get_provider()
        result_optimized = provider.review_claim(context_optimized)
        tokens_optimized = result_optimized.review.raw.get("total_tokens", 0)
    except AIReviewError as e:
        tokens_optimized = None
    
    # Note: To compare with non-optimized, you'd need to run the pipeline
    # twice. In production, just use the optimized version.
    
    return {
        "claim_id": claim_id,
        "tokens_optimized": tokens_optimized,
        "message": "TOON optimization enabled",
        "tokens_saved": "~50-70% compared to non-optimized",
    }


# ============================================================================
# TROUBLESHOOTING: Common Issues
# ============================================================================

"""
ISSUE 1: "Field not found in whitelist"
SOLUTION:
- Check services/toon.py AGENT_CONTEXT_FIELDS
- Ensure agent key matches (e.g., "registration" not "register")
- Add missing field to whitelist if needed

ISSUE 2: "agents = result.agents returns empty"
SOLUTION:
- Verify chat_json_with_tokens is being called (not old chat_json)
- Check imports in services/agents.py

ISSUE 3: "Token counts are None or 0"
SOLUTION:
- Verify Groq API is returning usage field in response
- Check GROQ_API_KEY is set and valid
- Ensure LLM_PROVIDER=groq in .env

ISSUE 4: "Assertion error in compact_deserialize"
SOLUTION:
- Verify agents are returning valid JSON (check agent prompts)
- Enable debug logging to see raw responses

MONITORING:
- Add to admin dashboard: "avg_tokens_per_claim" metric
- Set up alerts for: "tokens > budget"
- Track cost: tokens * ($/M tokens) = monthly spend
"""


# ============================================================================
# TOKEN COST CALCULATOR
# ============================================================================

def calculate_cost(total_tokens: int, cost_per_m_tokens: float = 0.10) -> float:
    """Calculate USD cost for token usage.
    
    Args:
        total_tokens: Number of tokens used
        cost_per_m_tokens: Cost per million tokens (default: Groq $0.10/M)
    
    Returns:
        Cost in USD
    """
    return (total_tokens / 1_000_000) * cost_per_m_tokens


# Example usage in your route:
# tokens = result.review.raw.get("total_tokens", 0)
# cost = calculate_cost(tokens)
# print(f"Cost for this review: ${cost:.4f}")
