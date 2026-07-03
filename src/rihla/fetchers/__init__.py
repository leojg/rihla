# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
fetchers - the price-fetch layer.

`PriceFetcher` is the seam (`quote`, optional `quote_calendar`). `MockFetcher` (offline),
`TravelpayoutsFetcher` (cached, licensed primary) and `SerpApiFetcher` (BYO-key real-data
fill) satisfy it; `CompositeFetcher` merges several via `merge_quotes`;
`CalendarCacheFetcher` TTL-caches a calendar-capable source's months. `build_grid` /
`fetch_leg` orchestrate fetching across a trip and are the only network-touching code;
their `_with_hints` variants also return the out-of-window `Observation`s that back the
result's `hints`.
"""
from rihla.core import Quote
from rihla.fetchers.base import (
    Observation,
    PriceFetcher,
    build_grid,
    build_grid_with_hints,
    fetch_leg,
    fetch_leg_with_hints,
)
from rihla.fetchers.cache import CalendarCacheFetcher
from rihla.fetchers.merge import CompositeFetcher, merge_quotes
from rihla.fetchers.mock import MockFetcher
from rihla.fetchers.serpapi import SerpApiFetcher
from rihla.fetchers.travelpayouts import TravelpayoutsFetcher

__all__ = [
    "PriceFetcher", "Quote", "Observation",
    "build_grid", "build_grid_with_hints", "fetch_leg", "fetch_leg_with_hints",
    "merge_quotes", "CompositeFetcher", "CalendarCacheFetcher",
    "MockFetcher", "TravelpayoutsFetcher", "SerpApiFetcher",
]
