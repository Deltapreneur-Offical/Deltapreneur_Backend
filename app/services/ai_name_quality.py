"""Heuristics to filter low-quality AI-generated brand names."""

from __future__ import annotations

import re

# Obvious filler suffixes that produce disconnected names (Coffexa, Foodora, etc.)
_WEAK_SUFFIXES = (
    "exa",
    "ixa",
    "ora",
    "tron",
    "tronix",
    "ify",
    "ly",
    "io",
    "ium",
    "ous",
    "etic",
    "ify",
    "scape",
    "verse",
    "hub",
)

_GENERIC_WORDS = frozenset(
    {
        "best",
        "online",
        "business",
        "platform",
        "solution",
        "solutions",
        "company",
        "service",
        "services",
        "global",
        "world",
        "smart",
        "pro",
        "app",
        "tech",
        "digital",
        "group",
        "corp",
        "hub",
        "24/7",
    },
)

_BANNED_PREFIXES = (
    "hub",
    "pro",
    "tech",
    "digital",
    "global",
    "online",
    "my",
    "the",
    "get",
    "go",
)

_BANNED_SUFFIXES = (
    "hub",
    "pro",
    "tech",
    "solutions",
    "digital",
    "global",
    "online",
    "services",
    "corp",
    "24/7",
    "ify",
    "tron",
    "tronix",
)

_INDUSTRY_ROOTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("coffee", "cafe", "espresso", "roast", "barista", "bean"), "coffee"),
    (("water", "aqua", "hydro", "spring", "mineral", "hydration"), "water"),
    (("fashion", "apparel", "clothing", "wear", "boutique", "garment", "style"), "fashion"),
    (("restaurant", "food", "meal", "kitchen", "chef", "dining", "bistro"), "food"),
    (("movie", "cinema", "film", "theatre", "theater", "ticket"), "entertainment"),
    (("learn", "school", "course", "education", "study", "tutor"), "education"),
    (("travel", "hotel", "flight", "trip", "tour"), "travel"),
    (("health", "fitness", "wellness", "clinic", "medical", "doctor"), "health"),
    (("finance", "payment", "bank", "money", "invest", "wealth"), "finance"),
    (("shop", "store", "retail", "boutique", "commerce", "ecommerce"), "retail"),
    (("construction", "builder", "building", "contractor", "renovation", "infrastructure"), "construction"),
)

_INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coffee": ("coffee", "brew", "bean", "roast", "cup", "cafe", "espresso", "mocha", "grind", "sip"),
    "water": ("water", "aqua", "hydro", "pure", "flow", "spring", "drop", "drink", "hydrate", "crystal", "fresh"),
    "fashion": ("fashion", "style", "wear", "cloth", "thread", "silk", "mode", "couture", "garment", "chic", "vogue"),
    "food": ("food", "bite", "table", "kitchen", "chef", "plate", "savor", "dine", "meal"),
    "education": ("learn", "study", "mind", "skill", "class", "mentor", "teach", "educ"),
    "entertainment": ("show", "film", "cinema", "screen", "stage", "play", "ticket"),
    "travel": ("travel", "trip", "journey", "voyage", "roam", "wander", "hotel"),
    "health": ("health", "well", "vital", "care", "heal", "fit", "life"),
    "finance": ("pay", "wealth", "capital", "fund", "cash", "money", "invest"),
    "retail": ("shop", "store", "cart", "market", "trade", "sell"),
    "construction": (
        "build",
        "struct",
        "frame",
        "stone",
        "steel",
        "mason",
        "craft",
        "site",
        "foundation",
        "mortar",
        "beam",
        "forge",
        "works",
        "core",
        "solid",
        "anchor",
        "erect",
        "construct",
    ),
}

# Related words AI uses for ideas that do not appear literally in the brand name.
_SEMANTIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "construction": _INDUSTRY_KEYWORDS["construction"],
    "construct": _INDUSTRY_KEYWORDS["construction"],
    "builder": ("build", "craft", "frame", "works", "forge"),
    "building": ("build", "struct", "frame", "stone", "steel"),
    "coffee": _INDUSTRY_KEYWORDS["coffee"],
    "water": _INDUSTRY_KEYWORDS["water"],
    "fashion": _INDUSTRY_KEYWORDS["fashion"],
    "delivery": ("flow", "route", "swift", "drop", "ship", "carry", "move", "dispatch"),
}


def detect_industry(idea: str) -> str:
    text = idea.lower()
    for terms, industry in _INDUSTRY_ROOTS:
        if any(term in text for term in terms):
            return industry
    return "general"


def _idea_keywords(idea: str) -> set[str]:
    tokens = set(re.findall(r"[a-z]{3,}", idea.lower()))
    industry = detect_industry(idea)
    extra = list(_INDUSTRY_KEYWORDS.get(industry, ()))
    return tokens | set(extra)


def is_hard_to_pronounce(name: str) -> bool:
    lower = name.lower()
    if re.search(r"(.)\1\1", lower):
        return True
    if re.search(r"[^aeiou]{5,}", lower):
        return True
    if len(lower) > 16:
        return True
    consonant_clusters = re.findall(r"[bcdfghjklmnpqrstvwxyz]{5,}", lower)
    return len(consonant_clusters) > 0


def is_generic_name(name: str) -> bool:
    lower = name.lower()
    return any(word in lower for word in _GENERIC_WORDS)


def has_banned_affix(name: str) -> bool:
    lower = name.lower()
    for prefix in _BANNED_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix) + 2:
            return True
    for suffix in _BANNED_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 2:
            return True
    if re.search(r"ai$", lower) and len(lower) >= 5:
        return True
    if lower.endswith("x") and len(lower) >= 5:
        return True
    return False


def exceeds_structure_cap(name: str, structure_roots: dict[str, int], *, cap: int = 2) -> bool:
    lower = name.lower()
    if len(lower) < 4:
        return False
    prefix_key = f"p:{lower[:4]}"
    suffix_key = f"s:{lower[-4:]}"
    return structure_roots.get(prefix_key, 0) >= cap or structure_roots.get(suffix_key, 0) >= cap


def record_structure(name: str, structure_roots: dict[str, int]) -> None:
    lower = name.lower()
    if len(lower) >= 4:
        prefix_key = f"p:{lower[:4]}"
        suffix_key = f"s:{lower[-4:]}"
        structure_roots[prefix_key] = structure_roots.get(prefix_key, 0) + 1
        structure_roots[suffix_key] = structure_roots.get(suffix_key, 0) + 1


_BAD_SHORT_TAILS = frozenset({"exa", "ixa", "ily", "ix", "ax", "ez", "io"})

_MEANINGFUL_TAILS = frozenset(
    {
        "nest",
        "haven",
        "craft",
        "house",
        "lab",
        "works",
        "bean",
        "brew",
        "roast",
        "cup",
        "republic",
        "reserve",
        "iq",
        "pop",
        "buzz",
    },
)


def is_lazy_industry_suffix(name: str, idea: str) -> bool:
    """
    Reject names that glue an industry keyword to a random suffix (Coffexa, Foodly).
    """
    lower = name.lower()
    keywords = _idea_keywords(idea)
    for kw in sorted(keywords, key=len, reverse=True):
        if len(kw) < 4 or not lower.startswith(kw[:4]):
            continue
        if lower.startswith(kw) and len(lower) <= len(kw) + 2:
            continue
        tail = lower[len(kw) :] if lower.startswith(kw) else lower[4:]
        if not tail or len(tail) < 2:
            continue
        if tail in _MEANINGFUL_TAILS or any(part in tail for part in _MEANINGFUL_TAILS):
            continue
        if any(tail.endswith(suffix) for suffix in _WEAK_SUFFIXES):
            return True
        if tail in _BAD_SHORT_TAILS:
            return True
    return False


def _semantic_signals(idea: str) -> set[str]:
    signals = set(_idea_keywords(idea))
    for token in re.findall(r"[a-z]{4,}", idea.lower()):
        signals.update(_SEMANTIC_EXPANSIONS.get(token, ()))
        if len(token) > 5:
            signals.update(_SEMANTIC_EXPANSIONS.get(token[:8].rstrip("s"), ()))
    return signals


def has_brand_signal(name: str, idea: str) -> bool:
    """Name should connect to the business idea via keywords or industry semantics."""
    lower = name.lower()
    signals = _semantic_signals(idea)
    if any(kw in lower for kw in signals if len(kw) >= 3):
        return True
    idea_tokens = [
        token
        for token in re.findall(r"[a-z]{4,}", idea.lower())
        if token not in _GENERIC_WORDS
    ]
    for token in idea_tokens:
        if lower.startswith(token[:4]) or token[:4] in lower:
            return True
    return False


def passes_name_quality(
    name: str,
    idea: str,
    *,
    ai_score: int,
    min_score: int = 80,
    from_ai: bool = False,
) -> bool:
    clean = re.sub(r"[^A-Za-z]", "", name)
    if len(clean) < 4 or len(clean) > 18:
        return False
    if ai_score < min_score:
        return False
    if is_hard_to_pronounce(clean):
        return False
    if is_generic_name(clean):
        return False
    if has_banned_affix(clean):
        return False
    if is_lazy_industry_suffix(clean, idea):
        return False
    # OpenRouter already scores relevance — trust high-scoring AI names.
    if from_ai and ai_score >= 80:
        return True
    if not has_brand_signal(clean, idea):
        return False
    return True
