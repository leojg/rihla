"""
fetchers - the price-fetch layer.

`PriceFetcher` is the protocol; `MockFetcher` (offline) and `AmadeusFetcher` (live)
satisfy it. `build_grid()` / `fetch_leg()` orchestrate fetching across a trip and
are the only network-touching code. Adding a source (e.g. Travelpayouts) is one
more module implementing the same protocol.
"""
from rihla.fetchers.amadeus import AmadeusFetcher
from rihla.fetchers.base import PriceFetcher, build_grid, fetch_leg
from rihla.fetchers.mock import MockFetcher

__all__ = ["PriceFetcher", "build_grid", "fetch_leg", "MockFetcher", "AmadeusFetcher"]
