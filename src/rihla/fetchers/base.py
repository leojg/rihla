"""
fetchers/base.py - the price-fetch protocol and grid-building orchestration.

`PriceFetcher` is the one-method seam every source implements: `quote(origin, dest, day)
-> Quote`. A source MAY also implement `quote_calendar(origin, dest, month) -> {date: Quote}`
to return a whole month in one call - Travelpayouts' calendar, the budget-collapsing path.
`fetch_leg` prefers the calendar and falls back to per-date `quote()` for sources that lack
it (SerpApi) or for routes the calendar source doesn't cover. When every source behind the
fetcher is calendar-capable, an empty calendar is authoritative - the per-date fallback
would just re-ask the same cache date-by-date, so it is skipped (ADR-0005).

The month calendars also see fares just OUTSIDE the leg window; instead of discarding
them, `build_grid_with_hints` keeps the nearest few per side as `Observation`s so an
unpriced leg can answer "would shifting the window help?" without another search.

`build_grid()` is the only code that makes the priced/quota-limited network calls
(place resolution in `resolve.py` is a second, quota-free boundary - ADR-0004);
everything the optimizer consumes downstream is pure local compute.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol

from rihla.core import Leg, PricedLeg, Quote, Trip

_HINTS_PER_SIDE = 3        # out-of-window dates kept per side of a leg's window


class PriceFetcher(Protocol):
    name: str

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]: ...
    # Optional, duck-typed capability (not required by the Protocol):
    #   def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]


@dataclass(frozen=True)
class Observation:
    """An out-of-window fare seen (and otherwise discarded) while fetching a leg.

    Fetch-layer telemetry, not optimizer input: these never enter the grid, they only
    surface as `hints` on partial/no_coverage results.
    """
    day: date
    origin: str
    dest: str
    quote: Quote


def _calendar_exhaustive(fetcher: PriceFetcher) -> bool:
    """True when every source behind `fetcher` is calendar-capable, so an empty
    calendar month is authoritative and per-date fallback would re-ask the same cache."""
    children = getattr(fetcher, "fetchers", None)      # CompositeFetcher duck-type
    return all(callable(getattr(f, "quote_calendar", None))
               for f in (children if children else [fetcher]))


def _months_in(earliest: date, latest: date) -> list[str]:
    """The YYYY-MM strings the [earliest, latest] window touches."""
    months: list[str] = []
    y, m = earliest.year, earliest.month
    while (y, m) <= (latest.year, latest.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return months


def _route_quotes(fetcher: PriceFetcher, origin: str, dest: str,
                  leg: Leg) -> tuple[dict[date, Quote], dict[date, Quote]]:
    """(in-window quotes by date, out-of-window quotes by date) for one (origin, dest).

    Calendar-first: if the fetcher exposes `quote_calendar`, pull each month the window
    touches in one call, keep the in-window dates and set aside the rest as observations.
    If the window yields nothing AND a non-calendar source exists behind the fetcher, fall
    back to per-date `quote()` over the sampled candidate dates - which, on a
    CompositeFetcher, reaches the real-data sources (SerpApi). When every source is
    calendar-capable, the empty month IS the answer (per-date would re-ask the same cache).
    Caveat: the month query is price-sorted and capped (limit=100 upstream), so on a very
    dense route an in-window date could in principle hide beyond the cap; accepted - the
    empty-calendar cache miss is the case that dominates in practice.
    """
    out: dict[date, Quote] = {}
    obs: dict[date, Quote] = {}
    cal = getattr(fetcher, "quote_calendar", None)
    if callable(cal):
        for month in _months_in(leg.earliest, leg.latest):
            for day, q in cal(origin, dest, month).items():
                bucket = out if leg.earliest <= day <= leg.latest else obs
                if day not in bucket or q.price < bucket[day].price:
                    bucket[day] = q
        if out or _calendar_exhaustive(fetcher):
            return out, obs
    for day in leg.candidate_dates():
        q = fetcher.quote(origin, dest, day)
        if q is not None and (day not in out or q.price < out[day].price):
            out[day] = q
    return out, obs


def fetch_leg_with_hints(fetcher: PriceFetcher,
                         leg: Leg) -> tuple[dict[date, PricedLeg], list[Observation]]:
    """Cheapest (origin, dest) pair per date for one leg, plus the nearest out-of-window
    observations (up to `_HINTS_PER_SIDE` dates before and after the window)."""
    grid: dict[date, PricedLeg] = {}
    seen: dict[date, Observation] = {}
    for o in leg.origin.airports:
        for d in leg.dest.airports:
            quotes, extras = _route_quotes(fetcher, o, d, leg)
            for day, q in quotes.items():
                best = grid.get(day)
                if best is None or q.price < best.price:
                    grid[day] = PricedLeg(leg.name, day, o, d, q.price, q.source,
                                          bookable=q.bookable, airline=q.airline,
                                          flight_number=q.flight_number, link=q.link,
                                          fetched_at=q.fetched_at)
            for day, q in extras.items():
                prev = seen.get(day)
                if prev is None or q.price < prev.quote.price:
                    seen[day] = Observation(day, o, d, q)
    before = sorted(d for d in seen if d < leg.earliest)[-_HINTS_PER_SIDE:]
    after = sorted(d for d in seen if d > leg.latest)[:_HINTS_PER_SIDE]
    return grid, [seen[d] for d in before + after]


def fetch_leg(fetcher: PriceFetcher, leg: Leg) -> dict[date, PricedLeg]:
    """Cheapest (origin, dest) pair per date for one leg."""
    return fetch_leg_with_hints(fetcher, leg)[0]


def build_grid_with_hints(fetcher: PriceFetcher, trip: Trip) -> tuple[
        dict[str, dict[date, PricedLeg]], dict[str, list[Observation]]]:
    """`build_grid` plus per-leg out-of-window observations (see `Observation`)."""
    grids: dict[str, dict[date, PricedLeg]] = {}
    hints: dict[str, list[Observation]] = {}
    for leg in trip.legs:
        grids[leg.name], hints[leg.name] = fetch_leg_with_hints(fetcher, leg)
    return grids, hints


def build_grid(fetcher: PriceFetcher, trip: Trip) -> dict[str, dict[date, PricedLeg]]:
    """The only place that hits the priced network (resolve.py is quota-free).
    Everything downstream is local."""
    return build_grid_with_hints(fetcher, trip)[0]
