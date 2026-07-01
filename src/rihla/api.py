"""
api.py - the search_trip seam: a serializable Query in, a serializable result dict out.

This is the single surface both the CLI and the future MCP server wrap. It turns an
untyped query (dict/JSON) into the domain model, drives the one network call
(`build_grid`), ranks with the pure optimizer, and serializes the result. It is
dependency-injected - the caller supplies the fetcher (`cli.choose_fetcher()`, or a
`MockFetcher` in tests) - so this module does no I/O of its own and no printing.

Result shape:
    {
      "status": "ok" | "partial" | "no_coverage" | "constraints_unsatisfiable",
      "missing_legs": [leg names with no priced dates],
      "options": [ {complete, total, currency, duration_days, legs: [...]}, ... ],
      "query": <the echoed query>,
    }

Ranking is price-only for v1; `optimize`'s `key=` seam is where a v2 weight function
(price + inter-city closeness, ...) would plug in. Complete itineraries always rank
first; partial ones (over the legs that WERE priced) are appended only as a fallback
when there are <= 1 complete options.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date

from rihla.core import Bundle, Place, PricedLeg, Trip, linear_trip, optimize, optimize_partial
from rihla.fetchers import build_grid
from rihla.places import resolve_stop


def _parse_iso(s, field_name: str) -> date:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be an ISO date (YYYY-MM-DD), got {s!r}") from None


@dataclass
class Query:
    """A flexible multi-leg query. `stops` is the ordered list of destinations after the
    origin; each stop is a region name (str) or a raw IATA-code list. `stays` gives the
    (min,max) nights at each intermediate stop, so len(stays) == len(stops) - 1."""
    origins: list
    stops: list
    earliest: str                    # ISO date - first-departure window start
    latest: str                      # ISO date - first-departure window end
    stays: list                      # per intermediate stop: (min_nights, max_nights)
    date_step: int = 3
    top: int = 5
    currency: str = "USD"
    adults: int = 1                  # carried + echoed; not yet threaded into fetchers (v1)

    def __post_init__(self):
        self.origins = [str(o).strip().upper() for o in self.origins]
        self.stops = [s if isinstance(s, str) else [str(c).strip().upper() for c in s]
                      for s in self.stops]
        self.stays = [tuple(s) for s in self.stays]
        if not self.origins:
            raise ValueError("query needs at least one origin airport")
        if len(self.stays) != len(self.stops) - 1:
            raise ValueError(
                f"need one (min,max) stay per intermediate stop: {len(self.stops)} stops "
                f"-> {len(self.stops) - 1} stays expected, got {len(self.stays)}")
        _parse_iso(self.earliest, "earliest")
        _parse_iso(self.latest, "latest")

    @classmethod
    def from_dict(cls, d: dict) -> "Query":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown query fields: {sorted(unknown)}; known: {sorted(known)}")
        try:
            return cls(
                origins=list(d["origins"]),
                stops=list(d["stops"]),
                earliest=d["earliest"],
                latest=d["latest"],
                stays=list(d["stays"]),
                date_step=int(d.get("date_step", 3)),
                top=int(d.get("top", 5)),
                currency=d.get("currency", "USD"),
                adults=int(d.get("adults", 1)),
            )
        except KeyError as e:
            raise ValueError(f"query missing required field: {e.args[0]!r}") from None

    def to_dict(self) -> dict:
        return {
            "origins": list(self.origins),
            "stops": [s if isinstance(s, str) else list(s) for s in self.stops],
            "earliest": self.earliest,
            "latest": self.latest,
            "stays": [list(s) for s in self.stays],
            "date_step": self.date_step,
            "top": self.top,
            "currency": self.currency,
            "adults": self.adults,
        }


def build_trip(query: Query) -> Trip:
    """Resolve a Query's places and derive the linear Trip (windows/gaps from stays)."""
    places = [Place("/".join(query.origins), tuple(query.origins))]
    places += [resolve_stop(s) for s in query.stops]
    return linear_trip(
        "search", places,
        _parse_iso(query.earliest, "earliest"), _parse_iso(query.latest, "latest"),
        stays=query.stays, date_step=query.date_step,
    )


def _bundle_key(b: Bundle) -> frozenset:
    return frozenset((p.leg, p.depart, p.origin, p.dest) for p in b.chosen.values())


def _leg_to_dict(p: PricedLeg) -> dict:
    return {
        "leg": p.leg,
        "from": p.origin,
        "to": p.dest,
        "date": p.depart.isoformat(),
        "airline": p.airline,
        "flight_number": p.flight_number,
        "price": round(p.price, 2),
        "source": p.source,
        "bookable": p.bookable,
        "link": p.link,
    }


def _bundle_to_dict(b: Bundle, leg_order: list, currency: str, n_legs: int) -> dict:
    complete = len(b.chosen) == n_legs
    return {
        "complete": complete,
        "total": round(b.total, 2),
        "currency": currency,
        # A partial that survives a missing MIDDLE leg spans a gap with no flight in it,
        # so a door-to-door duration would be a lie -> null unless complete.
        "duration_days": b.duration_days if complete else None,
        "legs": [_leg_to_dict(b.chosen[n]) for n in leg_order if n in b.chosen],
    }


def assemble_result(trip: Trip, grid: dict, top: int = 5, currency: str = "USD") -> dict:
    """Rank + serialize a (trip, grid) into `{status, missing_legs, options}`.

    Pure over the already-fetched grid (no I/O) - the ranking/status core of search_trip,
    factored out so the full-before-partial rule and the status vocabulary are testable
    with a hand-built grid (e.g. the constraints_unsatisfiable path a linear query can't
    reach). Complete itineraries always rank first; partials (over the priced legs) are
    appended only when there are <= 1 complete options.
    """
    leg_order = [leg.name for leg in trip.legs]
    missing = [n for n in leg_order if not grid[n]]
    n_legs = len(trip.legs)

    full = optimize(trip, grid, top=top)
    options = list(full)
    if len(full) <= 1:                       # fall back to partials only when full is thin
        seen = {_bundle_key(b) for b in full}
        for b in optimize_partial(trip, grid, top=top):
            k = _bundle_key(b)
            if k not in seen:
                seen.add(k)
                options.append(b)
    options = options[:top]

    if any(len(b.chosen) == n_legs for b in options):
        status = "ok"
    elif options:
        status = "partial"
    elif missing:
        status = "no_coverage"
    else:
        status = "constraints_unsatisfiable"

    return {
        "status": status,
        "missing_legs": missing,
        "options": [_bundle_to_dict(b, leg_order, currency, n_legs) for b in options],
    }


def search_trip(query, fetcher) -> dict:
    """Run a query against a fetcher and return a serializable result dict.

    `query` may be a Query or a raw dict; `fetcher` is any PriceFetcher (injected).
    """
    q = query if isinstance(query, Query) else Query.from_dict(query)
    trip = build_trip(q)
    grid = build_grid(fetcher, trip)
    return {**assemble_result(trip, grid, top=q.top, currency=q.currency), "query": q.to_dict()}
