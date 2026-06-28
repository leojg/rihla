"""
cli.py - run a query from the command line.

This is the only layer that does user-facing I/O (reading env / printing). Keeping
print() out of core and fetchers matters: an MCP server speaking over stdio would
have its transport corrupted by stray stdout. The MCP wrapper will reuse
build_grid() + optimize() directly and serialize the result instead of printing.
"""
from __future__ import annotations

import os

from rihla.core import optimize
from rihla.fetchers import AmadeusFetcher, MockFetcher, PriceFetcher, build_grid
from rihla.places import example_trip


def choose_fetcher() -> PriceFetcher:
    """Pick the live Amadeus fetcher if credentials are present, else go offline."""
    cid, secret = os.getenv("AMADEUS_CLIENT_ID"), os.getenv("AMADEUS_CLIENT_SECRET")
    if cid and secret:
        return AmadeusFetcher(cid, secret)
    print("(no AMADEUS_* env vars set - using offline MockFetcher)\n")
    return MockFetcher()


def main() -> None:
    # Load a local .env if python-dotenv is installed; harmless if it isn't.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    trip = example_trip()
    fetcher = choose_fetcher()

    worst_calls = sum(len(l.origin.airports) * len(l.dest.airports) * len(l.candidate_dates())
                      for l in trip.legs)
    print(trip.name)
    print(f"{len(trip.legs)} legs | worst-case uncached API calls this run: {worst_calls}\n")

    grid = build_grid(fetcher, trip)
    best = optimize(trip, grid, top=5)
    if not best:
        print("No valid itinerary (a leg returned no priced dates - widen windows or check coverage).")
    for i, b in enumerate(best, 1):
        print(f"{i}. ${b.total:,.0f}   ({b.duration_days} days door-to-door)")
        for leg in trip.legs:
            p = b.chosen[leg.name]
            print(f"     {p.origin} -> {p.dest}   {p.depart:%a %d-%b}    ${p.price:,.0f}")
        print()


if __name__ == "__main__":
    main()
