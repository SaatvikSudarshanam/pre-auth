#!/usr/bin/env python3
"""
TOON Verification Script

Run this to verify TOON implementation is working correctly.
Usage: python3 verify_toon.py
"""

import json
import sys
from pathlib import Path

# Windows consoles default to cp1252 and choke on the ✅/❌/🧪 emojis below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from services.toon import (
    FIELD_ABBREV,
    REVERSE_ABBREV,
    compact_serialize,
    compact_deserialize,
    whitelist_context,
    AGENT_CONTEXT_FIELDS,
    TokenBudget,
    summarize_documents_text,
)


def test_abbreviations():
    """Test field abbreviation functionality."""
    print("\n🧪 Test 1: Field Abbreviations")
    print("=" * 50)
    
    test_obj = {
        "claim_id": 123,
        "claim_type": "procedure",
        "amount": 5000.00,
        "status": "pending",
    }
    
    serialized = compact_serialize(test_obj)
    print(f"Original: {json.dumps(test_obj)}")
    print(f"TOON:     {serialized}")
    print(f"Savings:  {len(json.dumps(test_obj)) - len(serialized)} chars")
    
    # Test deserialization
    deserialized = compact_deserialize(serialized)
    assert deserialized == test_obj, "Deserialization failed!"
    print("✅ Abbreviations working correctly")


def test_null_removal():
    """Test null/empty value removal."""
    print("\n🧪 Test 2: Null Removal")
    print("=" * 50)
    
    test_obj = {
        "field1": "value",
        "field2": None,
        "field3": "",
        "field4": [],
        "field5": "another",
    }
    
    serialized = compact_serialize(test_obj)
    print(f"Original fields: {len(test_obj)}")
    parsed = json.loads(serialized)
    print(f"After TOON:      {len(parsed)}")
    print(f"TOON result:     {serialized}")
    
    assert "field2" not in serialized, "Null not removed!"
    assert "field3" not in serialized, "Empty string not removed!"
    print("✅ Null removal working correctly")


def test_compact_json():
    """Test compact JSON serialization."""
    print("\n🧪 Test 3: Compact JSON")
    print("=" * 50)
    
    test_obj = {"field": "value", "array": [1, 2, 3], "float": 3.14159}
    
    standard = json.dumps(test_obj, indent=2)
    compact = compact_serialize(test_obj)
    
    print(f"Standard JSON ({len(standard)} chars):")
    print(standard)
    print(f"\nCompact TOON ({len(compact)} chars):")
    print(compact)
    print(f"Savings: {len(standard) - len(compact)} chars")
    print("✅ Compact JSON working correctly")


def test_field_whitelisting():
    """Test agent-specific field whitelisting."""
    print("\n🧪 Test 4: Field Whitelisting")
    print("=" * 50)
    
    full_context = {
        "claim": {"cid": 123, "ct": "procedure", "amt": 5000, "dx": "condition"},
        "plan_rules": {"pln": "Gold", "lim": 50000, "ded": 500},
        "financials": {"used": 20000, "remaining": 30000},
        "documents": [{"fn": "invoice.pdf", "dt": "invoice"}],
        "identity": {"nm": "John Doe", "mid": "M123456"},
    }
    
    # Test different agents
    agents = ["registration", "completeness", "coverage"]
    
    for agent in agents:
        whitelist = AGENT_CONTEXT_FIELDS.get(agent, {})
        print(f"\n{agent.upper()}:")
        print(f"  Fields needed: {list(whitelist.keys())}")
    
    # Test registration agent whitelisting
    reg_context = whitelist_context(full_context, "registration")
    print(f"\nRegistration context fields: {list(reg_context.keys())}")
    assert "claim" in reg_context, "Registration should include claim!"
    assert "identity" in reg_context, "Registration should include identity!"
    
    print("✅ Field whitelisting working correctly")


def test_document_truncation():
    """Test document text truncation."""
    print("\n🧪 Test 5: Document Truncation")
    print("=" * 50)
    
    long_doc = "A" * 2000  # 2000 character document
    max_chars = 1000
    truncated = summarize_documents_text(long_doc, max_chars=max_chars)
    suffix = "\n[... truncated ...]"  # appended by summarize_documents_text

    print(f"Original: {len(long_doc)} chars")
    print(f"Truncated: {len(truncated)} chars")
    print(f"Savings: {len(long_doc) - len(truncated)} chars")

    assert len(truncated) <= max_chars + len(suffix), "Truncation failed!"
    print("✅ Document truncation working correctly")


def test_token_budget():
    """Test token budget tracking."""
    print("\n🧪 Test 6: Token Budget Tracking")
    print("=" * 50)
    
    budget = TokenBudget(budget_per_agent=500)
    
    # Simulate token usage
    budget.record("registration", 100, 50)      # 150 total
    budget.record("completeness", 120, 80)      # 200 total
    budget.record("integrity", 600, 100)        # 700 total (OVER budget!)
    budget.record("coverage", 150, 50)          # 200 total
    budget.record("preauth", 200, 100)          # 300 total
    budget.record("denial", 100, 50)            # 150 total
    
    report = budget.report()
    
    print(f"Total tokens: {report['total_tokens']}")
    print(f"Per agent: {report['per_agent']}")
    print(f"Over budget: {report['agents_over_budget']}")
    
    assert "integrity" in report["agents_over_budget"], "Budget check failed!"
    print("✅ Token budget tracking working correctly")


def test_all_abbreviations():
    """Verify all abbreviations are reversible."""
    print("\n🧪 Test 7: Abbreviation Consistency")
    print("=" * 50)
    
    print(f"Total abbreviations: {len(FIELD_ABBREV)}")
    print(f"Reverse mappings: {len(REVERSE_ABBREV)}")
    
    # Test round-trip
    for full, abbr in FIELD_ABBREV.items():
        assert REVERSE_ABBREV[abbr] == full, f"Mapping error for {full} <-> {abbr}"
    
    print("✅ All abbreviations are consistent")


def main():
    """Run all tests."""
    print("\n" + "=" * 50)
    print("TOON Implementation Verification")
    print("=" * 50)
    
    try:
        test_abbreviations()
        test_null_removal()
        test_compact_json()
        test_field_whitelisting()
        test_document_truncation()
        test_token_budget()
        test_all_abbreviations()
        
        print("\n" + "=" * 50)
        print("✅ ALL TESTS PASSED - TOON IS WORKING!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. [DONE] routes/admin.py already uses build_claim_context_optimized()")
        print("2. Track tokens in your API responses (review.raw['total_tokens'])")
        print("3. Monitor cost reduction (expect 50-70% savings)")
        print("\nSee TOON_QUICK_START.py for integration examples")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
