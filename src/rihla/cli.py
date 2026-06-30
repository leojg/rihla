"""
cli.py - run a query from the command line.

The only layer that does user-facing I/O (reading env / printing). Keeping print() out of
core and fetchers matters: an MCP server over stdio would have its transport corrupted by
stray stdout. The MCP wrapper will reuse build_grid() + optimize() and serialize instead.
"""
from __future__ import annotations

import os

from rihla.core import optimize
from rihla.fetchers import (
    CompositeFetcher,
    MockFetcher,
    PriceFetcher,
    SerpApiFetcher,
    TravelpayoutsFetcher,
    build_grid,
)
from rihla.places import example_trip


def choose_fetcher() -> PriceFetcher:
    """Build the data source from RIHLA_PROFILE + whatever keys are present.

    local  (default): every source whose key is set, incl. SerpApi BYOK.
    hosted          : redistribution-licensed sources only (SerpApi disabled).
    mock            : force the offline MockFetcher.
    """
    profile = os.getenv("RIHLA_PROFILE", "local").strip().lower()
    if profile == "mock":
        print("(RIHLA_PROFILE=mock - offline MockFetcher)\n")
        return MockFetcher()

    fetchers: list[PriceFetcher] = []
    if os.getenv("TRAVELPAYOUTS_TOKEN"):
        fetchers.append(TravelpayoutsFetcher(os.environ["TRAVELPAYOUTS_TOKEN"]))
    if os.getenv("SERPAPI_KEY"):
        if profile == "hosted":
            print("(profile=hosted - SerpApi disabled: licensed sources only)")
        else:
            fetchers.append(SerpApiFetcher(os.environ["SERPAPI_KEY"]))

    if not fetchers:
        print("(no data-source keys set - offline MockFetcher)\n")
        return MockFetcher()
    print(f"(profile={profile} | sources: {', '.join(f.name for f in fetchers)})\n")
    return CompositeFetcher(fetchers) if len(fetchers) > 1 else fetchers[0]


def main() -> None:
    # Load a local .env if python-dotenv is installed; harmless if it isn't.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    trip = example_trip()
    fetcher = choose_fetcher()
    print(trip.name)
    print(f"{len(trip.legs)} legs (calendar-first; per-date fallback only on uncovered routes)\n")

    grid = build_grid(fetcher, trip)
    best = optimize(trip, grid, top=5)
    if not best:
        print("No valid itinerary - a leg returned no priced dates. Widen the windows, add a "
              "source (e.g. SERPAPI_KEY for thin routes like Tokyo->South America), or check coverage.")
    for i, b in enumerate(best, 1):
        print(f"{i}. ${b.total:,.0f}   ({b.duration_days} days door-to-door)")
        for leg in trip.legs:
            p = b.chosen[leg.name]
            print(f"     {p.origin} -> {p.dest}   {p.depart:%a %d-%b}    ${p.price:,.0f}  [{p.source}]")
        print()


if __name__ == "__main__":
    main()
