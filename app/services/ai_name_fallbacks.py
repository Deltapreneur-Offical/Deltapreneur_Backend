"""Curated industry-aware fallback names when OpenRouter is slow or unavailable."""

from __future__ import annotations

from app.schemas.ai_domains import AIDomainCandidate
from app.services.ai_name_quality import detect_industry

# (name, style, score, reason)
_CURATED: dict[str, tuple[tuple[str, str, int, str], ...]] = {
    "coffee": (
        ("BrewNest", "Modern Startup", 93, "Warm, memorable name tying brew culture to a gathering place"),
        ("RoastIQ", "Modern Startup", 91, "Signals quality roasting with a smart, modern edge"),
        ("Beanova", "Modern Startup", 90, "Fresh startup feel rooted in coffee beans"),
        ("Sipora", "Gen Z Brand", 89, "Playful, social, easy to say for younger audiences"),
        ("VelvetRoast", "Premium Cafe", 94, "Premium roast positioning with sensory warmth"),
        ("OakBean", "Premium Cafe", 92, "Natural, craft-cafe tone with bean heritage"),
        ("EmberCup", "Luxury", 91, "Luxury warmth — ember heat and the ritual of the cup"),
        ("NoirRoast", "Luxury", 90, "Dark, sophisticated roast house aesthetic"),
        ("BrewHaven", "Premium Cafe", 92, "Inviting third-place cafe energy"),
        ("MorningRoast", "Premium Cafe", 88, "Clear coffee occasion — morning ritual"),
        ("Cupster", "Gen Z Brand", 87, "Casual, friendly Gen Z cafe brand"),
        ("RoastLab", "Gen Z Brand", 88, "Experimental specialty coffee vibe"),
        ("Aurelo", "Global Brand", 95, "Short, premium, globally pronounceable coffee brand"),
        ("Cavela", "Global Brand", 94, "Distinctive global brand with soft premium tone"),
        ("Rovya", "Global Brand", 92, "Modern global name suitable for franchise growth"),
        ("Nexora", "Global Brand", 91, "Contemporary brand with scale-up potential"),
        ("Brewly", "Modern Startup", 90, "Simple startup-friendly coffee app or chain name"),
        ("SipCraft", "Premium Cafe", 89, "Craft coffee with a light, modern feel"),
        ("BeanRepublic", "Global Brand", 88, "Bold coffee community and scale narrative"),
        ("Velari", "Luxury", 93, "Elegant, short luxury cafe or roastery name"),
    ),
    "food": (
        ("Savora", "Premium Dining", 92, "Taste-forward name for a memorable dining brand"),
        ("TableOak", "Premium Dining", 90, "Warm hospitality with natural craft positioning"),
        ("BiteCraft", "Modern Startup", 89, "Food delivery or kitchen startup friendly"),
        ("Plateful", "Modern Startup", 88, "Clear meal offering with friendly tone"),
        ("ChefNest", "Premium Dining", 91, "Chef-led kitchen with welcoming identity"),
        ("Zesto", "Gen Z Brand", 87, "Energetic food brand for younger customers"),
        ("Nuvio", "Global Brand", 93, "Short global food or restaurant brand"),
        ("Rovya", "Global Brand", 91, "Distinctive name for franchise restaurant concepts"),
    ),
    "education": (
        ("Mentra", "Modern Startup", 92, "Mentorship and learning in one short brand"),
        ("Skillora", "Modern Startup", 90, "Skills platform with approachable tone"),
        ("LearnNest", "Premium", 89, "Safe learning hub with warmth"),
        ("Edvya", "Modern Startup", 88, "Ed-tech startup with crisp pronunciation"),
        ("Lunari", "Global Brand", 91, "Aspirational education brand with global appeal"),
    ),
    "general": (
        ("Aurelo", "Global Brand", 94, "Short premium startup name with global appeal"),
        ("Nexora", "Global Brand", 92, "Modern scale-up brand sound"),
        ("Velari", "Luxury", 93, "Elegant brand suitable for premium positioning"),
        ("Cavela", "Global Brand", 91, "Distinctive and memorable coined brand"),
        ("Rovya", "Global Brand", 90, "Modern brand with franchise potential"),
        ("Meraki", "Premium", 89, "Soulful brand for customer-centric businesses"),
        ("Solvi", "Modern Startup", 88, "Clean SaaS or service startup name"),
    ),
}


def curated_candidates(idea: str, industry_category: str) -> list[AIDomainCandidate]:
    industry = detect_industry(idea)
    rows = _CURATED.get(industry) or _CURATED["general"]
    candidates: list[AIDomainCandidate] = []
    for name, style, score, reason in rows:
        candidates.append(
            AIDomainCandidate(
                name=name,
                style=style,
                score=score,
                reason=reason,
                category=industry_category,
            ),
        )
    return candidates
