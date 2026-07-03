# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
fetchers/merge.py - multi-source merge.

`merge_quotes` is the cross-source rule: prefer the cheapest **bookable** quote; only if
no source returned a bookable fare fall back to the cheapest indicative/cached hint. So a
stale Travelpayouts cache price can never out-rank a real SerpApi fare.

`CompositeFetcher` wraps several sources behind the same `PriceFetcher` seam, so
`build_grid`/`fetch_leg` stay source-agnostic. Its `quote_calendar` aggregates only the
calendar-capable sources (Travelpayouts); `fetch_leg` falls back to per-date `quote()` -
which reaches every source - for routes the calendar doesn't cover.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from rihla.core import Quote


def merge_quotes(quotes: list[Optional[Quote]]) -> Optional[Quote]:
    qs = [q for q in quotes if q is not None]
    if not qs:
        return None
    bookable = [q for q in qs if q.bookable]
    return min(bookable or qs, key=lambda q: q.price)


class CompositeFetcher:
    """Queries several sources and merges their quotes per (origin, dest, day)."""
    name = "composite"

    def __init__(self, fetchers):
        self.fetchers = list(fetchers)

    @property
    def sources(self) -> list[str]:
        """Child source names, for result provenance (`api._sources_of`)."""
        return [f.name for f in self.fetchers]

    @property
    def currency(self) -> Optional[str]:
        """The one currency every declaring child serves (canonical upper), else None.

        None (unknown/mixed) disables the currency guard in `api.search_trip`; a mixed
        composite is a wiring bug `build_fetcher` can't produce, so it isn't policed here.
        """
        declared = {str(c).strip().upper()
                    for c in (getattr(f, "currency", None) for f in self.fetchers) if c}
        return declared.pop() if len(declared) == 1 else None

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        return merge_quotes([f.quote(origin, dest, day) for f in self.fetchers])

    def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]:
        out: dict[date, Quote] = {}
        for f in self.fetchers:
            cal = getattr(f, "quote_calendar", None)
            if not callable(cal):
                continue
            for day, q in cal(origin, dest, month).items():
                out[day] = merge_quotes([out.get(day), q])
        return out
