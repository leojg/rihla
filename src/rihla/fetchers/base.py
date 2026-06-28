"""
fetchers/base.py - the price-fetch protocol and the grid-building orchestration.

`PriceFetcher` is the one-method seam every data source implements. `build_grid()`
is the ONLY function in the project that touches the network; everything the
optimizer consumes downstream is pure local compute over the grid it returns.
This is the clean boundary the future MCP tool wraps.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Protocol

from rihla.core import Leg, PricedLeg, Trip


class PriceFetcher(Protocol):
    def price(self, origin: str, dest: str, day: date) -> Optional[float]: ...


def fetch_leg(fetcher: PriceFetcher, leg: Leg) -> dict[date, PricedLeg]:
    """Cheapest (origin, dest) pair per sampled date for one leg."""
    grid: dict[date, PricedLeg] = {}
    for d in leg.candidate_dates():
        best: Optional[PricedLeg] = None
        for o in leg.origin.airports:
            for dst in leg.dest.airports:
                p = fetcher.price(o, dst, d)
                if p is not None and (best is None or p < best.price):
                    best = PricedLeg(leg.name, d, o, dst, p)
        if best is not None:
            grid[d] = best
    return grid


def build_grid(fetcher: PriceFetcher, trip: Trip) -> dict[str, dict[date, PricedLeg]]:
    """The ONLY place that hits the network. Everything downstream is local."""
    return {leg.name: fetch_leg(fetcher, leg) for leg in trip.legs}
