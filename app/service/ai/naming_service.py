from __future__ import annotations

import re


class NamingService:
    """Deterministic naming helper used before the LLM enriches recommendations."""

    SUFFIXES = ("ly", "io", "base", "nest", "labs", "grid", "flow", "wise", "vault")
    PREFIXES = ("Nova", "Astra", "Cred", "Luxe", "Nexa", "Vanta", "Omni", "Co", "Prime")

    def generate_candidates(self, prompt: str, limit: int = 8) -> list[dict[str, str]]:
        words = [w.title() for w in re.findall(r"[a-zA-Z]{3,}", prompt)[:6]]
        seeds = words or ["Brand", "Market", "Venture"]
        names: list[dict[str, str]] = []
        for index, seed in enumerate(seeds):
            prefix = self.PREFIXES[index % len(self.PREFIXES)]
            suffix = self.SUFFIXES[index % len(self.SUFFIXES)]
            for name in (f"{prefix}{seed}", f"{seed}{suffix.title()}"):
                names.append(
                    {
                        "name": name,
                        "domain_hint": f"{name.lower()}.com",
                        "reasoning": "Short, pronounceable, and suitable for a premium marketplace or startup brand.",
                    }
                )
                if len(names) >= limit:
                    return names
        return names[:limit]
