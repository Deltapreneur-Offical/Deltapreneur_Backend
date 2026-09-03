"""Tests for AI brand name quality heuristics."""

from app.services.ai_name_quality import (
    detect_industry,
    has_banned_affix,
    is_lazy_industry_suffix,
    passes_name_quality,
)


def test_detect_industry_coffee():
    assert detect_industry("Coffee Shop downtown") == "coffee"


def test_rejects_lazy_coffee_suffixes():
    idea = "Coffee Shop"
    for bad in ("Coffexa", "Coffily", "Coffora", "Coffio"):
        assert is_lazy_industry_suffix(bad, idea)
        assert not passes_name_quality(bad, idea, ai_score=95)


def test_accepts_relevant_coffee_names():
    idea = "Coffee Shop"
    for good in ("BrewNest", "VelvetRoast", "OakBean", "RoastIQ"):
        assert passes_name_quality(good, idea, ai_score=90)


def test_rejects_generic_coined_names_for_unrelated_ideas():
    for idea in ("Water Delivery", "Fashion Brand"):
        for bad in ("Aurelo", "Nexora", "Cavela", "Rovya"):
            assert not passes_name_quality(bad, idea, ai_score=95)


def test_rejects_low_ai_score():
    assert not passes_name_quality("BrewNest", "Coffee Shop", ai_score=79)


def test_rejects_banned_affixes():
    for bad in ("CoffeeHub", "BrewPro", "BeanTech", "RoastSolutions", "CafeGlobal", "SipOnline"):
        assert has_banned_affix(bad)
        assert not passes_name_quality(bad, "Coffee Shop", ai_score=95)


def test_construction_semantic_names_pass():
    idea = "construction"
    for good in ("BuildCraft", "StoneForge", "Structura", "IronBeam"):
        assert passes_name_quality(good, idea, ai_score=90, from_ai=True)


def test_ai_trusts_high_scores_without_literal_keyword():
    assert passes_name_quality("Meridian", "construction", ai_score=88, from_ai=True)
