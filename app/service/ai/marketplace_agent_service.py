from __future__ import annotations

import re
from typing import Any


ACTION_LABELS = {
    "analyze": "Analyze",
    "bid_strategy": "Bid Strategy",
    "buy": "Buy",
    "contact": "Contact",
    "connect": "Connect",
    "contact_owner": "Contact Owner",
    "view_listing": "View Listing",
    "view": "View",
    "view_auction": "View Auction",
    "watch": "Watch",
    "explore": "Explore",
    "match_startup": "Match to Startup",
    "place_bid": "Place Bid",
    "contact_seller": "Contact Seller",
    "add_to_favorites": "Add to Favorites",
    "generate_logo": "Generate Logo",
}


class MarketplaceAgentService:
    """Deterministic marketplace agent layer built only from database results."""

    def enrich(
        self,
        *,
        message: str,
        context: dict[str, Any],
        user_activity: dict[str, Any] | None,
        voice_requested: bool = False,
    ) -> dict[str, Any]:
        marketplace = context.get("marketplace") or {}
        domains = [self._with_actions(item) for item in marketplace.get("domains", [])]
        ventures = [self._with_actions(item) for item in marketplace.get("ventures", [])]
        creators = [self._with_actions(item) for item in marketplace.get("creators", [])]
        auctions = [self._with_actions(item) for item in marketplace.get("auctions", [])]
        software = [self._with_actions(item) for item in marketplace.get("software", [])]

        for domain in domains:
            domain["analysis"] = self.analyze_domain(domain)
            domain["analysis"]["similar_alternatives"] = [
                {"asset_id": other.get("id"), "name": other.get("name"), "price": other.get("price")}
                for other in domains
                if other.get("id") != domain.get("id")
            ][:3]
            domain["investment_confidence"] = self.investment_confidence(domain)
            domain["estimated_resale_value_range"] = self.estimated_resale_value_range(domain)

        all_listings = [*domains, *ventures, *creators, *auctions, *software]
        agent = {
            "database_first": True,
            "primary_truth": "real_database_marketplace_results",
            "confidence": self.confidence(context, all_listings),
            "source_citations": self.source_citations(all_listings),
            "actions": self._collect_actions(all_listings),
            "domain_analysis": [item["analysis"] for item in domains],
            "domain_comparison": self.compare_domains(domains),
            "auction_recommendations": self.recommend_auctions(auctions),
            "creator_discovery": self.discover_creators(creators, user_activity),
            "venture_matches": self.match_ventures(ventures, user_activity),
            "personalized_recommendations": self.personalized_recommendations(
                all_listings,
                user_activity,
            ),
            "founder_plan": self.founder_plan(context.get("mode"), message, domains, ventures, creators, software),
            "suggested_followups": self.suggested_followups(context, domains, auctions, ventures, creators),
            "voice_reply": self.voice_reply(message, context, user_activity, voice_requested),
            "user_favorites": (user_activity or {}).get("favorite_labels", []),
        }

        context["marketplace"] = {
            "domains": domains,
            "ventures": ventures,
            "creators": creators,
            "auctions": auctions,
            "software": software,
            "technologies": software,
        }
        context["marketplace_counts"] = self.marketplace_counts(context["marketplace"])
        context["marketplace_categories"] = self.marketplace_categories(all_listings)
        context["listing_status"] = self.listing_status(all_listings)
        context["marketplace_analytics"] = self.marketplace_analytics(all_listings)
        context["no_matching_records"] = not any(context["marketplace_counts"].values())
        context["agent"] = agent
        context["personalization"]["activity"] = user_activity or {}
        return context

    def analyze_domain(self, item: dict[str, Any]) -> dict[str, Any]:
        name = str(item.get("name") or "")
        stem = name.split(".")[0].lower()
        extension = "." + name.split(".", 1)[1].lower() if "." in name else ""
        length_score = max(0, 100 - abs(len(stem) - 8) * 7)
        vowel_ratio = self._vowel_ratio(stem)
        pronounceable = 80 if 0.25 <= vowel_ratio <= 0.55 else 58
        penalties = 0
        penalties += 18 if "-" in stem else 0
        penalties += 12 if any(char.isdigit() for char in stem) else 0
        penalties += 10 if len(stem) > 15 else 0
        extension_bonus = 14 if extension == ".com" else 7 if extension in {".ai", ".io", ".co"} else 0
        category = str(item.get("category") or "").lower()
        tags = " ".join(str(tag).lower() for tag in item.get("tags") or [])
        industry_terms = f"{category} {tags}"
        startup_bonus = 12 if any(term in industry_terms for term in ["tech", "ai", "saas", "finance", "brand"]) else 4
        brand_score = self._clamp(round((length_score + pronounceable) / 2 + extension_bonus + startup_bonus - penalties))
        memorability = self._clamp(round(length_score + extension_bonus - penalties / 2))
        seo_potential = self._clamp(round(62 + extension_bonus + min(18, len((item.get("tags") or [])) * 4) - penalties / 2))
        commercial_value = self._clamp(round(brand_score + min(18, float(item.get("price") or 0) / 25000) + (10 if extension == ".com" else 3) - penalties / 3))
        startup_potential = self._clamp(round(brand_score + startup_bonus - max(0, float(item.get("price") or 0) / 50000)))
        industry_fit = self._industry_fit(stem, category, tags)
        pronunciation = "strong" if pronounceable >= 80 and penalties < 15 else "moderate" if pronounceable >= 58 else "difficult"
        pronunciation_score = self._clamp(pronounceable - penalties / 2 + extension_bonus / 2)
        score_breakdown = {
            "brandability": {
                "score": brand_score,
                "explanation": self._score_explanation("brandability", brand_score, extension, penalties),
            },
            "memorability": {
                "score": memorability,
                "explanation": self._score_explanation("memorability", memorability, extension, penalties),
            },
            "seo_potential": {
                "score": seo_potential,
                "explanation": self._score_explanation("SEO potential", seo_potential, extension, penalties),
            },
            "pronunciation": {
                "score": pronunciation_score,
                "label": pronunciation,
                "explanation": self._score_explanation("pronunciation", pronunciation_score, extension, penalties),
            },
            "commercial_value": {
                "score": commercial_value,
                "explanation": self._score_explanation("commercial value", commercial_value, extension, penalties),
            },
        }
        return {
            "asset_id": item.get("id"),
            "name": item.get("name"),
            "brand_score": brand_score,
            "memorability": memorability,
            "seo_potential": seo_potential,
            "pronunciation": pronunciation,
            "pronunciation_score": pronunciation_score,
            "commercial_value": commercial_value,
            "startup_potential": startup_potential,
            "industry_fit": industry_fit,
            "score_breakdown": score_breakdown,
            "explanations": {key: value["explanation"] for key, value in score_breakdown.items()},
            "summary": self._domain_summary(brand_score, memorability, pronunciation, industry_fit),
        }

    def compare_domains(self, domains: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(domains) < 2:
            return None
        ranked = sorted(
            domains,
            key=lambda item: (
                (item.get("analysis") or {}).get("brand_score", 0),
                (item.get("analysis") or {}).get("memorability", 0),
                -float(item.get("price") or 0),
            ),
            reverse=True,
        )
        return {
            "winner": ranked[0].get("name"),
            "reason": "Highest combined brand score, memorability, and marketplace fit from database results.",
            "ranked": [
                {
                    "asset_id": item.get("id"),
                    "name": item.get("name"),
                    "price": item.get("price"),
                    "brand_score": (item.get("analysis") or {}).get("brand_score"),
                    "memorability": (item.get("analysis") or {}).get("memorability"),
                    "startup_potential": (item.get("analysis") or {}).get("startup_potential"),
                }
                for item in ranked[:5]
            ],
        }

    def recommend_auctions(self, auctions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored = []
        for item in auctions:
            seconds_left = item.get("seconds_left")
            urgency = 30 if seconds_left is not None and seconds_left < 86400 else 15
            activity = min(30, int(item.get("total_bids") or 0) * 5)
            price = float(item.get("price") or item.get("min_bid_price") or 0)
            price_discipline = 25 if price <= 100000 else 15 if price <= 500000 else 8
            score = self._clamp(urgency + activity + price_discipline + 25)
            scored.append(
                {
                    "asset_id": item.get("id"),
                    "name": item.get("name"),
                    "auction_type": item.get("auction_type"),
                    "score": score,
                    "current_bid": item.get("price"),
                    "ends_at": item.get("ends_at"),
                    "reason": self._auction_reason(score, seconds_left, item.get("total_bids")),
                    "url": item.get("url"),
                }
            )
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:5]

    def discover_creators(
        self,
        creators: list[dict[str, Any]],
        user_activity: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        interests = self._interest_terms(user_activity)
        discovered = []
        for item in creators:
            haystack = self._listing_text(item)
            overlap = len([term for term in interests if term and term in haystack])
            score = self._clamp(55 + overlap * 12 + min(20, len(item.get("tags") or []) * 3))
            discovered.append(
                {
                    "asset_id": item.get("id"),
                    "name": item.get("name"),
                    "role": item.get("role"),
                    "category": item.get("category"),
                    "score": score,
                    "reason": "Matches your marketplace interests." if overlap else "Strong creator profile from approved community listings.",
                    "url": item.get("url"),
                }
            )
        return sorted(discovered, key=lambda item: item["score"], reverse=True)[:5]

    def match_ventures(
        self,
        ventures: list[dict[str, Any]],
        user_activity: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        interests = self._interest_terms(user_activity)
        matches = []
        for item in ventures:
            haystack = self._listing_text(item)
            overlap = len([term for term in interests if term and term in haystack])
            featured = 8 if item.get("is_featured") else 0
            score = self._clamp(58 + overlap * 10 + featured)
            matches.append(
                {
                    "asset_id": item.get("id"),
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "score": score,
                    "deal_value": item.get("price"),
                    "reason": "Aligned with your saved activity and stated interests." if overlap else "Relevant active venture from the marketplace.",
                    "url": item.get("url"),
                }
            )
        return sorted(matches, key=lambda item: item["score"], reverse=True)[:5]

    def personalized_recommendations(
        self,
        listings: list[dict[str, Any]],
        user_activity: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        interests = self._interest_terms(user_activity)
        recs = []
        for item in listings:
            haystack = self._listing_text(item)
            overlap = len([term for term in interests if term and term in haystack])
            featured = 10 if item.get("is_featured") else 0
            score = self._clamp(50 + overlap * 14 + featured)
            recs.append(
                {
                    "asset_id": item.get("id"),
                    "asset_type": item.get("type"),
                    "name": item.get("name"),
                    "score": score,
                    "reason": "Personalized from your preferences, saved items, and recent AI activity." if interests else "Recommended from current marketplace results.",
                    "url": item.get("url"),
                }
            )
        return sorted(recs, key=lambda item: item["score"], reverse=True)[:6]

    def voice_reply(
        self,
        message: str,
        context: dict[str, Any],
        user_activity: dict[str, Any] | None,
        voice_requested: bool,
    ) -> dict[str, Any]:
        enabled = bool(voice_requested or (context.get("personalization") or {}).get("voice_enabled"))
        return {
            "enabled": enabled,
            "style": "concise spoken marketplace brief",
            "instruction": (
                "When voice is enabled, answer in short natural sentences and mention only the strongest listing names."
            ),
            "suggested_intro": "I checked the live marketplace first." if enabled else None,
        }

    def _with_actions(self, item: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(item)
        enriched["actions"] = self.actions_for(enriched)
        enriched["badges"] = self.badges_for(enriched)
        enriched["price_trend"] = self.price_trend(enriched)
        enriched["investment_confidence"] = self.investment_confidence(enriched)
        enriched["estimated_resale_value_range"] = self.estimated_resale_value_range(enriched)
        return enriched

    def badges_for(self, item: dict[str, Any]) -> list[str]:
        asset_type = item.get("type")
        price = float(item.get("price") or item.get("min_bid_price") or 0)
        badges: list[str] = []
        if asset_type == "auction":
            badges.append("Auction")
        elif price:
            badges.append("Buy Now")
        else:
            badges.append("Negotiation")
        if item.get("is_featured"):
            badges.append("Featured")
        return badges

    def price_trend(self, item: dict[str, Any]) -> dict[str, Any]:
        price = float(item.get("price") or item.get("min_bid_price") or 0)
        bids = int(item.get("total_bids") or 0)
        if item.get("type") == "auction" and bids > 2:
            return {"direction": "up", "label": "Rising demand", "basis": "active bidding"}
        if price and price <= 100000:
            return {"direction": "steady", "label": "Accessible entry", "basis": "current listed price"}
        if price:
            return {"direction": "premium", "label": "Premium ask", "basis": "current listed price"}
        return {"direction": "unknown", "label": "Seller quote needed", "basis": "no public price"}

    def investment_confidence(self, item: dict[str, Any]) -> dict[str, Any]:
        analysis = item.get("analysis") or {}
        base = int(analysis.get("brand_score") or 58)
        featured = 8 if item.get("is_featured") else 0
        activity = min(12, int(item.get("total_bids") or 0) * 3)
        score = self._clamp(base + featured + activity)
        label = "High" if score >= 78 else "Medium" if score >= 58 else "Speculative"
        return {"score": score, "label": label}

    def estimated_resale_value_range(self, item: dict[str, Any]) -> dict[str, Any] | None:
        price = float(item.get("price") or item.get("min_bid_price") or 0)
        if not price:
            return None
        confidence = (item.get("investment_confidence") or {}).get("score") or 60
        low_multiplier = 1.15 if confidence >= 75 else 0.9
        high_multiplier = 1.75 if confidence >= 75 else 1.35
        return {
            "low": round(price * low_multiplier),
            "high": round(price * high_multiplier),
            "basis": "heuristic estimate from current listing price and marketplace signals",
        }

    def confidence(self, context: dict[str, Any], listings: list[dict[str, Any]]) -> dict[str, Any]:
        if not context.get("requires_database", True):
            return {"score": 80, "label": "Guidance", "reason": "This request is platform guidance or strategy and does not require marketplace records."}
        if context.get("marketplace_unavailable"):
            return {"score": 25, "label": "Low", "reason": "Marketplace context was unavailable."}
        if not listings:
            return {"score": 45, "label": "Limited", "reason": "No matching marketplace listings were found."}
        score = self._clamp(62 + min(24, len(listings) * 4))
        label = "High" if score >= 78 else "Medium"
        return {"score": score, "label": label, "reason": "Based on live marketplace matches and deterministic scoring."}

    def source_citations(self, listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "label": item.get("name"),
                "source": "HubRegistrar marketplace database",
                "asset_type": item.get("type"),
                "asset_id": item.get("id"),
                "url": item.get("url") or self._default_url(item),
            }
            for item in listings[:6]
            if item.get("name")
        ]

    def marketplace_counts(self, marketplace: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        return {
            "domains": len(marketplace.get("domains") or []),
            "auctions": len(marketplace.get("auctions") or []),
            "ventures": len(marketplace.get("ventures") or []),
            "technologies": len(marketplace.get("software") or marketplace.get("technologies") or []),
            "creators": len(marketplace.get("creators") or []),
        }

    def marketplace_categories(self, listings: list[dict[str, Any]]) -> list[str]:
        categories = []
        for item in listings:
            category = item.get("category")
            if category and category not in categories:
                categories.append(str(category))
        return categories[:12]

    def listing_status(self, listings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        statuses: dict[str, list[dict[str, Any]]] = {}
        for item in listings:
            asset_type = str(item.get("type") or "unknown")
            statuses.setdefault(asset_type, []).append(
                {
                    "asset_id": item.get("id"),
                    "name": item.get("name"),
                    "status": item.get("listing_status") or item.get("status"),
                }
            )
        return statuses

    def marketplace_analytics(self, listings: list[dict[str, Any]]) -> dict[str, Any]:
        prices = [float(item.get("price") or 0) for item in listings if float(item.get("price") or 0) > 0]
        return {
            "total_results": len(listings),
            "featured_results": len([item for item in listings if item.get("is_featured")]),
            "total_views": sum(int(item.get("views") or 0) for item in listings),
            "live_auction_count": len([item for item in listings if item.get("type") == "auction"]),
            "average_price": round(sum(prices) / len(prices), 2) if prices else None,
        }

    def suggested_followups(
        self,
        context: dict[str, Any],
        domains: list[dict[str, Any]],
        auctions: list[dict[str, Any]],
        ventures: list[dict[str, Any]],
        creators: list[dict[str, Any]],
    ) -> list[str]:
        suggestions: list[str] = []
        if domains:
            suggestions.append(f"Compare {domains[0].get('name')} with similar domains")
            suggestions.append(f"Generate logo direction for {domains[0].get('name')}")
        if auctions:
            suggestions.append("How do auctions work?")
            suggestions.append("Show active domain auctions")
        if ventures or creators:
            suggestions.append("Find collaboration opportunities that match my profile")
        suggestions.extend(
            [
                "How do I list my domain for sale?",
                "Generate startup names",
                "Build a brand identity",
                "Contact HubRegistrar support",
            ]
        )
        return suggestions[:4]

    def founder_plan(
        self,
        mode: str | None,
        message: str,
        domains: list[dict[str, Any]],
        ventures: list[dict[str, Any]],
        creators: list[dict[str, Any]],
        software: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if mode != "founder" and not re.search(r"\b(build me a startup|startup plan|launch plan|business idea|build a saas|suggest a business)\b", message.lower()):
            return None
        domain = domains[0] if domains else None
        venture = ventures[0] if ventures else None
        creator = creators[0] if creators else None
        tool = software[0] if software else None
        return {
            "domain": domain.get("name") if domain else None,
            "business_idea": self._business_idea(domain, venture, tool),
            "branding": f"Lead with {domain.get('name')} as the trust anchor." if domain else "Use a short, category-clear name until a matching domain appears.",
            "monetization": "Start with a paid pilot, then expand into subscription or managed-service revenue.",
            "launch_plan": [
                "Validate one painful buyer problem.",
                "Secure or shortlist the marketplace asset.",
                "Ship a one-page offer and collect first customer conversations.",
                "Use creator or venture partners for distribution if they appear in results.",
            ],
            "collaboration": creator.get("name") if creator else None,
        }

    def actions_for(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        url = item.get("url") or self._default_url(item)
        asset_type = item.get("type")
        action_sets = {
            "domain": [
                {"type": "view", "label": ACTION_LABELS["view"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "buy", "label": ACTION_LABELS["buy"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "contact_seller", "label": ACTION_LABELS["contact_seller"], "url": f"/contact?asset={item.get('id')}", "asset_type": asset_type, "asset_id": item.get("id")},
            ],
            "auction": [
                {"type": "view_auction", "label": ACTION_LABELS["view_auction"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "place_bid", "label": ACTION_LABELS["place_bid"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "watch", "label": ACTION_LABELS["watch"], "asset_type": asset_type, "asset_id": item.get("id")},
            ],
            "venture": [
                {"type": "view", "label": ACTION_LABELS["view"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "contact_owner", "label": ACTION_LABELS["contact_owner"], "url": f"/contact?asset={item.get('id')}", "asset_type": asset_type, "asset_id": item.get("id")},
            ],
            "creator": [
                {"type": "view_listing", "label": "View Profile", "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "connect", "label": ACTION_LABELS["connect"], "url": f"/contact?asset={item.get('id')}", "asset_type": asset_type, "asset_id": item.get("id")},
            ],
            "software": [
                {"type": "view_listing", "label": "View Software", "url": url, "asset_type": asset_type, "asset_id": item.get("id")},
                {"type": "contact_seller", "label": ACTION_LABELS["contact_seller"], "url": f"/contact?asset={item.get('id')}", "asset_type": asset_type, "asset_id": item.get("id")},
            ],
        }
        return action_sets.get(asset_type, [{"type": "view_listing", "label": ACTION_LABELS["view_listing"], "url": url, "asset_type": asset_type, "asset_id": item.get("id")}])

    def _collect_actions(self, listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions = []
        for item in listings[:8]:
            for action in item.get("actions") or []:
                actions.append({**action, "asset_name": item.get("name")})
        return actions

    def _interest_terms(self, user_activity: dict[str, Any] | None) -> set[str]:
        if not user_activity:
            return set()
        raw: list[str] = []
        for key in ("favorite_categories", "domain_interests", "venture_interests", "favorite_labels", "recent_queries"):
            value = user_activity.get(key) or []
            if isinstance(value, str):
                raw.append(value)
            else:
                raw.extend(str(item) for item in value)
        return {term for item in raw for term in re.findall(r"[a-z0-9]+", item.lower()) if len(term) > 2}

    def _listing_text(self, item: dict[str, Any]) -> str:
        return " ".join(
            str(part or "")
            for part in [
                item.get("name"),
                item.get("category"),
                item.get("description"),
                item.get("role"),
                " ".join(str(tag) for tag in item.get("tags") or []),
            ]
        ).lower()

    def _vowel_ratio(self, value: str) -> float:
        letters = [char for char in value if char.isalpha()]
        if not letters:
            return 0
        vowels = [char for char in letters if char in "aeiou"]
        return len(vowels) / len(letters)

    def _industry_fit(self, stem: str, category: str, tags: str) -> str:
        text = f"{stem} {category} {tags}"
        if any(term in text for term in ["ai", "data", "tech", "cloud", "code", "app"]):
            return "technology and AI"
        if any(term in text for term in ["pay", "fin", "bank", "wealth", "capital"]):
            return "fintech and finance"
        if any(term in text for term in ["health", "med", "care", "well"]):
            return "health and wellness"
        if any(term in text for term in ["brand", "media", "creator", "studio"]):
            return "creator and brand-led businesses"
        return category.upper() if category else "general startup use"

    def _domain_summary(self, brand_score: int, memorability: int, pronunciation: str, industry_fit: str) -> str:
        if brand_score >= 82:
            quality = "premium"
        elif brand_score >= 68:
            quality = "solid"
        else:
            quality = "speculative"
        return f"{quality} domain with {memorability}/100 memorability, {pronunciation} pronunciation, and fit for {industry_fit}."

    def _score_explanation(self, label: str, score: int, extension: str, penalties: int) -> str:
        strength = "strong" if score >= 78 else "moderate" if score >= 58 else "limited"
        extension_note = f"{extension} extension support" if extension else "no extension advantage"
        penalty_note = "clean naming structure" if penalties == 0 else "reduced by length, digit, or hyphen friction"
        return f"{strength.title()} {label} from {extension_note} and {penalty_note}."

    def _business_idea(
        self,
        domain: dict[str, Any] | None,
        venture: dict[str, Any] | None,
        software: dict[str, Any] | None,
    ) -> str:
        if venture:
            return f"Use {venture.get('name')} as the starting opportunity and validate a focused paid offer."
        if software:
            return f"Package {software.get('name')} into a niche SaaS or service-assisted product."
        if domain:
            fit = ((domain.get("analysis") or {}).get("industry_fit")) or domain.get("category") or "startup"
            return f"Build a focused {fit} offer around {domain.get('name')}."
        return "Start with a service-led MVP, then buy the best-fit domain once demand is proven."

    def _auction_reason(self, score: int, seconds_left: Any, bids: Any) -> str:
        if seconds_left is not None and seconds_left < 86400:
            return "Ending soon; evaluate bid ceiling before entering."
        if int(bids or 0) > 0:
            return "Has bidding activity; useful signal but keep price discipline."
        if score >= 75:
            return "Low activity and reasonable timing make it worth watching."
        return "Watchlist candidate; bid only if it fits your exact use case."

    def _default_url(self, item: dict[str, Any]) -> str:
        asset_type = item.get("type")
        if asset_type == "domain":
            return f"/domains?listing={item.get('id')}"
        if asset_type == "venture":
            return f"/ventures?venture={item.get('id')}"
        if asset_type == "creator":
            return f"/community?creator={item.get('id')}"
        if asset_type == "software":
            return f"/cocreation?software={item.get('id')}"
        if asset_type == "auction":
            return f"/auction/{item.get('id')}"
        return "/"

    def _clamp(self, value: int | float) -> int:
        return max(0, min(100, int(value)))
