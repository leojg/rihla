"""
fetchers/base.py - the price-fetch protocol and grid-building orchestration.

`PriceFetcher` is the one-method seam every source implements: `quote(origin, dest, day)
-> Quote`. A source MAY also implement `quote_calendar(origin, dest, month) -> {date: Quote}`
to return a whole month in one call - Travelpayouts' calendar, the budget-collapsing path.
`fetch_leg` prefers the calendar and falls back to per-date `quote()` for sources that lack
it (SerpApi) or for routes the calendar source doesn't cover.

`build_grid()` is the ONLY code that touches the network; everything the optimizer consumes
downstream is pure local compute.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Protocol

from rihla.core import Leg, PricedLeg, Quote, Trip


class PriceFetcher(Protocol):
    name: str

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]: ...
    # Optional, duck-typed capability (not required by the Protocol):
    #   def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]


def _months_in(earliest: date, latest: date) -> list[str]:
    """The YYYY-MM strings the [earliest, latest] window touches."""
    months: list[str] = []
    y, m = earliest.year, earliest.month
    while (y, m) <= (latest.year, latest.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return months


def _route_quotes(fetcher: PriceFetcher, origin: str, dest: str, leg: Leg) -> dict[date, Quote]:
    """Quotes by date for one (origin, dest) over the leg window.

    Calendar-first: if the fetcher exposes `quote_calendar`, pull each month the window
    touches in one call and keep the in-window dates. If that yields nothing for this route
    (e.g. a Travelpayouts cache miss), fall back to per-date `quote()` over the sampled
    candidate dates - which, on a CompositeFetcher, reaches the real-data sources.
    """
    out: dict[date, Quote] = {}
    cal = getattr(fetcher, "quote_calendar", None)
    if callable(cal):
        for month in _months_in(leg.earliest, leg.latest):
            for day, q in cal(origin, dest, month).items():
                if leg.earliest <= day <= leg.latest and (day not in out or q.price < out[day].price):
                    out[day] = q
        if out:
            return out
    for day in leg.candidate_dates():
        q = fetcher.quote(origin, dest, day)
        if q is not None and (day not in out or q.price < out[day].price):
            out[day] = q
    return out


def fetch_leg(fetcher: PriceFetcher, leg: Leg) -> dict[date, PricedLeg]:
    """Cheapest (origin, dest) pair per date for one leg."""
    grid: dict[date, PricedLeg] = {}
    for o in leg.origin.airports:
        for d in leg.dest.airports:
            for day, q in _route_quotes(fetcher, o, d, leg).items():
                best = grid.get(day)
                if best is None or q.price < best.price:
                    grid[day] = PricedLeg(leg.name, day, o, d, q.price, q.source)
    return grid


def build_grid(fetcher: PriceFetcher, trip: Trip) -> dict[str, dict[date, PricedLeg]]:
    """The ONLY place that hits the network. Everything downstream is local."""
    return {leg.name: fetch_leg(fetcher, leg) for leg in trip.legs}
