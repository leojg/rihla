"""
fetchers/mock.py - offline fetcher with plausible prices, for development.

No network, no credentials: per-route base fare + weekday effect + noise. Lets the
whole pipeline (build_grid -> optimize -> output) run today without an Amadeus key.
"""
from __future__ import annotations

import random
from datetime import date
from typing import Optional


class MockFetcher:
    """Plausible offline prices: per-route base + weekday effect + noise."""
    def __init__(self, seed: int = 11):
        self._rng = random.Random(seed)
        self._base: dict[tuple[str, str], float] = {}

    def price(self, origin: str, dest: str, day: date) -> Optional[float]:
        b = self._base.setdefault((origin, dest), self._rng.uniform(450, 1500))
        wd = 1.15 if day.weekday() in (4, 6) else 0.92 if day.weekday() in (1, 2) else 1.0
        return round(b * wd * self._rng.uniform(0.85, 1.2))
