# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
fetchers/mock.py - offline fetcher with plausible prices, for development.

No network, no credentials: per-route base fare + weekday effect + noise. Lets the whole
pipeline (build_grid -> optimize -> output) run with no keys. Quotes are bookable=False.
"""
from __future__ import annotations

import random
import zlib
from datetime import date
from typing import Optional

from rihla.core import Quote

_AIRLINES = ("IB", "AF", "LH", "KL", "TP", "AZ", "UX", "AA")


def _synth_airline(origin: str, dest: str) -> tuple[str, str]:
    """Deterministic (stable across runs) carrier + flight number for a route."""
    h = zlib.crc32(f"{origin}>{dest}".encode())
    code = _AIRLINES[h % len(_AIRLINES)]
    return code, f"{code}{100 + h % 900}"


class MockFetcher:
    """Plausible offline prices: per-route base + weekday effect + noise."""
    name = "mock"

    def __init__(self, seed: int = 11):
        self._rng = random.Random(seed)
        self._base: dict[tuple[str, str], float] = {}

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        b = self._base.setdefault((origin, dest), self._rng.uniform(450, 1500))
        wd = 1.15 if day.weekday() in (4, 6) else 0.92 if day.weekday() in (1, 2) else 1.0
        airline, flight_number = _synth_airline(origin, dest)
        return Quote(round(b * wd * self._rng.uniform(0.85, 1.2)), self.name,
                     bookable=False, airline=airline, flight_number=flight_number)
