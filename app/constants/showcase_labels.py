"""Label sources for Random Premium generation (no seed labels required).

OpenProvider has no "list random premium domains" API, so Random mode
auto-generates candidate labels and runs the SAME batched availability check
the keyword flow uses. These lists are intentionally modest and brandable;
the generator is deterministic when seeded (tests) and random when unseeded
(production). All labels are lowercased and alphanumeric-only.
"""

from __future__ import annotations

import random

_ADJECTIVES = [
    "bright", "crisp", "swift", "prime", "nova", "luma", "peak", "clear",
    "bold", "pure", "zen", "echo", "quantum", "pixel", "neon", "cloud",
    "sky", "moon", "star", "vertex", "aurora", "blaze", "drift", "ember",
    "flux", "glide", "harbor", "iris", "jade", "kite", "lark", "mint",
    "onyx", "pine", "quartz", "raven", "sage", "tide", "umbra", "vivid",
    "willow", "amber", "breeze", "cedar", "delta", "frost", "grove",
]

_NOUNS = [
    "byte", "craft", "deck", "edge", "forge", "grid", "hub", "ink", "jolt",
    "key", "loop", "map", "node", "orbit", "pulse", "ray", "scope", "sync",
    "trace", "unit", "view", "wave", "yield", "zone", "core", "dock",
    "frame", "gate", "helm", "lane", "mesh", "nest", "ocean", "path",
    "quest", "root", "span", "token", "vault", "web", "axis", "beam",
    "cell", "dawn", "fuse",
]

_SYLLABLES = [
    "ka", "ro", "lu", "mi", "na", "pe", "so", "te", "va", "ze", "bar",
    "don", "fel", "gor", "hal", "jin", "kel", "mar", "nil", "por", "ren",
    "sil", "tor", "ven", "wor", "yul", "zan", "bel", "cam", "dor",
]

_RNG = random.Random()


def generate_random_labels(limit: int, *, seed: int | None = None) -> list[str]:
    """Produce up to ``limit`` unique, lowercase, alphanumeric candidate labels.

    Sources, in order: adjective+noun blends, syllabic compositions, then
    word+number fallbacks — deduplicated. Deterministic when ``seed`` is given
    (used by tests); unseeded in production for fresh pools each run.
    """
    limit = max(1, min(int(limit), 500))
    rng = random.Random(seed) if seed is not None else _RNG
    labels: list[str] = []
    seen: set[str] = set()

    def _add(word: str) -> None:
        w = "".join(ch for ch in str(word).lower() if ch.isalnum())
        if len(w) >= 4 and w not in seen:
            seen.add(w)
            labels.append(w)

    adj = list(_ADJECTIVES)
    nouns = list(_NOUNS)
    rng.shuffle(adj)
    rng.shuffle(nouns)
    # Standalone dictionary roots first. Concatenations like "brightbyte.com"
    # are almost never registry-premium; short words (mint, nova, harbor)
    # are what OpenProvider actually marks Premium across io/ai/co/…
    singles = adj + nouns
    rng.shuffle(singles)
    for w in singles:
        _add(w)
        if len(labels) >= limit:
            return labels
    for a in adj:
        for n in nouns:
            _add(a + n)
            if len(labels) >= limit:
                return labels

    syl = list(_SYLLABLES)
    rng.shuffle(syl)
    for s1 in syl:
        for s2 in syl:
            _add(s1 + s2)
            if len(labels) >= limit:
                return labels

    base = list(seen)
    rng.shuffle(base)
    for w in base:
        for num in (1, 2, 3, 7, 9):
            _add(f"{w}{num}")
            if len(labels) >= limit:
                return labels
    return labels
