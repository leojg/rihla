"""
core.py - data model + the pure optimizer.

This module has NO dependency on anything else in `rihla`. It defines the trip
domain model (places, legs, gaps, priced legs, bundles) and `optimize()`, which
enumerates valid date combinations over an already-fetched price grid and ranks
them by total cost. It performs no I/O and is fully testable in isolation.

The network-touching fetch layer lives in `rihla.fetchers` (which imports this
module), keeping the I/O boundary one-directional and clean for the future MCP
wrapper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product
from typing import Optional


# ------------------------------------------------------------------ model --

@dataclass(frozen=True)
class Place:
    """A named location that may resolve to several airports."""
    name: str
    airports: tuple[str, ...]


@dataclass(frozen=True)
class Leg:
    name: str
    origin: Place
    dest: Place
    earliest: date
    latest: date
    date_step: int = 3              # sample every N days to bound API calls

    def candidate_dates(self) -> list[date]:
        span = (self.latest - self.earliest).days
        return [self.earliest + timedelta(days=i)
                for i in range(0, span + 1, self.date_step)]


@dataclass(frozen=True)
class Gap:
    """Days between the departure of `before` and the departure of `after`."""
    before: str
    after: str
    min_days: int = 0
    max_days: Optional[int] = None


@dataclass(frozen=True)
class Quote:
    """A price for one (origin, dest, day) from a single source.

    `bookable` separates a real, bookable fare (e.g. SerpApi / Google Flights) from an
    indicative cached hint (e.g. Travelpayouts' search-history cache). The merge layer
    uses it so a stale cached price can't out-rank a real one.
    """
    price: float
    source: str
    bookable: bool = False
    fetched_at: Optional[str] = None    # ISO8601, optional freshness marker


@dataclass(frozen=True)
class PricedLeg:
    leg: str
    depart: date
    origin: str                     # winning airport within the origin set
    dest: str                       # winning airport within the dest set
    price: float
    source: str = "?"               # which data source won this (origin, dest, day)


@dataclass
class Trip:
    name: str
    legs: list[Leg]
    gaps: list[Gap]


@dataclass
class Bundle:
    chosen: dict[str, PricedLeg]

    @property
    def total(self) -> float:
        return sum(p.price for p in self.chosen.values())

    @property
    def duration_days(self) -> int:
        ds = [p.depart for p in self.chosen.values()]
        return (max(ds) - min(ds)).days


def linear_trip(name: str, places: list[Place],
                first_earliest: date, first_latest: date,
                stays: list[tuple[int, int]], date_step: int = 3) -> Trip:
    """
    places: ordered stops, e.g. [MVD_AREA, EUROPE, TOKYO, MVD_AREA] -> 3 legs.
    stays:  (min,max) nights at each INTERMEDIATE stop (len == len(places)-2).
    Downstream leg windows + gaps are derived from the first window and the
    stays, so you only specify the first departure window and the durations.
    """
    assert len(stays) == len(places) - 2, "need one (min,max) stay per intermediate stop"
    legs: list[Leg] = []
    gaps: list[Gap] = []
    earliest, latest = first_earliest, first_latest
    for i in range(len(places) - 1):
        legs.append(Leg(f"leg{i+1}", places[i], places[i + 1], earliest, latest, date_step))
        if i < len(stays):
            smin, smax = stays[i]
            gaps.append(Gap(f"leg{i+1}", f"leg{i+2}", smin, smax))
            earliest, latest = earliest + timedelta(days=smin), latest + timedelta(days=smax)
    return Trip(name, legs, gaps)


# --------------------------------------------------------------- optimize --

def _valid(departs: dict[str, date], gaps: list[Gap]) -> bool:
    for g in gaps:
        delta = (departs[g.after] - departs[g.before]).days
        if delta < g.min_days or (g.max_days is not None and delta > g.max_days):
            return False
    return True


def optimize(trip: Trip, grid: dict[str, dict[date, PricedLeg]], top: int = 5) -> list[Bundle]:
    names = [l.name for l in trip.legs]
    if any(not grid[n] for n in names):
        return []                           # some leg had no priced dates at all
    options = [list(grid[n].values()) for n in names]
    out: list[Bundle] = []
    for combo in product(*options):
        chosen = dict(zip(names, combo))
        if _valid({n: pl.depart for n, pl in chosen.items()}, trip.gaps):
            out.append(Bundle(chosen))
    out.sort(key=lambda b: b.total)
    return out[:top]
