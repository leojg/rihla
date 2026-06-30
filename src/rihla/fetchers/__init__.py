"""
fetchers - the price-fetch layer.

`PriceFetcher` is the seam (`quote`, optional `quote_calendar`). `MockFetcher` (offline),
`TravelpayoutsFetcher` (cached, licensed primary) and `SerpApiFetcher` (BYO-key real-data
fill) satisfy it; `CompositeFetcher` merges several via `merge_quotes`. `build_grid` /
`fetch_leg` orchestrate fetching across a trip and are the only network-touching code.
"""
from rihla.core import Quote
from rihla.fetchers.base import PriceFetcher, build_grid, fetch_leg
from rihla.fetchers.merge import CompositeFetcher, merge_quotes
from rihla.fetchers.mock import MockFetcher
from rihla.fetchers.serpapi import SerpApiFetcher
from rihla.fetchers.travelpayouts import TravelpayoutsFetcher

__all__ = [
    "PriceFetcher", "Quote", "build_grid", "fetch_leg", "merge_quotes",
    "CompositeFetcher", "MockFetcher", "TravelpayoutsFetcher", "SerpApiFetcher",
]
