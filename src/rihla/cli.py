"""
cli.py - run a query from the command line.

The only layer that does user-facing I/O (reading env / a query file / printing). Keeping
print() out of core/fetchers/api matters: an MCP server over stdio would have its transport
corrupted by stray stdout. This is a thin adapter over `search_trip` - the same seam the
future MCP server wraps.

Usage:
  python -m rihla.cli [query.json]      # no arg -> the canonical Uruguay->Europe->Tokyo trip
"""
from __future__ import annotations

import json
import os
import sys

from rihla.api import search_trip
from rihla.fetchers import (
    CompositeFetcher,
    MockFetcher,
    PriceFetcher,
    SerpApiFetcher,
    TravelpayoutsFetcher,
)
from rihla.places import REGIONS

# The §4 canonical query, as the default when no query file is given.
CANONICAL_QUERY = {
    "origins": ["MVD", "EZE", "AEP"],
    "stops": ["EUROPE", ["NRT", "HND"], "MVD_AREA"],
    "earliest": "2026-09-08",
    "latest": "2026-09-22",
    "stays": [[20, 30], [15, 15]],
    "date_step": 3,
    "top": 5,
}


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


def _fmt_leg(leg: dict, show_links: bool = False) -> str:
    carrier = leg["airline"] or "?"
    if leg["flight_number"]:
        carrier = f"{carrier} {leg['flight_number']}"
    tag = leg["source"] if leg["bookable"] else f"{leg['source']}, cached"
    # Fixed-width columns first (so prices align); variable-length carrier trails,
    # since real SerpApi airline names ("Sichuan Airlines ...") overflow any fixed pad.
    line = (f"{leg['from']:>3} -> {leg['to']:<3}  {leg['date']}  "
            f"${leg['price']:>7,.0f}  [{tag}]  {carrier}")
    if show_links and leg["link"]:      # links are long; opt in with --links
        line += f"\n            book: {leg['link']}"
    return line


def _print_result(res: dict, show_links: bool = False) -> None:
    status = res["status"]
    if status == "no_coverage":
        legs = ", ".join(res["missing_legs"])
        print(f"No prices found for any leg ({legs}). Widen the windows, add a source "
              "(e.g. SERPAPI_KEY for thin routes like Tokyo->South America), or check coverage.")
        return
    if status == "constraints_unsatisfiable":
        print("All legs priced, but no date combination satisfies the stay constraints. "
              "Widen the stays or the first-departure window.")
        return
    if status == "partial":
        legs = ", ".join(res["missing_legs"])
        print(f"PARTIAL - no complete itinerary. Couldn't price: {legs}. "
              "Best combinations over the legs that were found:\n")

    total_legs = len(res["options"][0]["legs"]) + len(res["missing_legs"]) if res["options"] else 0
    for i, opt in enumerate(res["options"], 1):
        meta = (f"{opt['duration_days']} days door-to-door" if opt["complete"]
                else f"partial: {len(opt['legs'])} of {total_legs} legs")
        print(f"{i}. {opt['total']:,.0f} {opt['currency']}   ({meta})")
        for leg in opt["legs"]:
            print("     " + _fmt_leg(leg, show_links))
        print()
    if not show_links and any(leg["link"] for opt in res["options"] for leg in opt["legs"]):
        print("(booking links hidden - re-run with --links to show them)")


def _parse_stop(s: str):
    """'EUROPE' -> region name; 'NRT,HND' or 'MAD' -> IATA-code list."""
    if "," in s:
        return [c.strip().upper() for c in s.split(",") if c.strip()]
    up = s.strip().upper()
    return up if up in REGIONS else [up]


def _parse_stay(s: str) -> list:
    """'20-30' -> [20, 30]; '15' -> [15, 15]."""
    s = s.strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return [int(a), int(b)]
    n = int(s)
    return [n, n]


def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    return input(f"{prompt}{hint}: ").strip() or default


def prompt_query() -> dict:
    """Build a query interactively (a friendlier alternative to hand-writing JSON)."""
    print("Interactive query - Ctrl-C to abort.  Regions:", ", ".join(sorted(REGIONS)), "\n")
    origins = [c.strip().upper() for c in _ask("Origin airports (comma-sep IATA, e.g. MVD,EZE,AEP)").split(",") if c.strip()]

    stops = []
    while True:
        s = _ask(f"Stop {len(stops) + 1} to visit (region name or IATA list; blank to finish)")
        if not s:
            if len(stops) < 1:
                print("  need at least one stop.")
                continue
            break
        stops.append(_parse_stop(s))

    # Round trip by default: append the origin as the final stop so there's a flight home.
    # (Say no for a one-way trip that just ends at the last stop.)
    if _ask(f"Round trip - return to {'/'.join(origins)}?", "yes").strip().lower() not in ("n", "no"):
        stops.append(list(origins))

    # A stay applies to every stop except the last (the final destination / home).
    stays = []
    for i, stop in enumerate(stops[:-1]):
        label = stop if isinstance(stop, str) else "/".join(stop)
        stays.append(_parse_stay(_ask(f"Nights at stop {i + 1} ({label}) - 'min-max' or 'n'")))

    query = {
        "origins": origins,
        "stops": stops,
        "earliest": _ask("Earliest departure (YYYY-MM-DD)"),
        "latest": _ask("Latest departure (YYYY-MM-DD)"),
        "stays": stays,
        "date_step": int(_ask("Date step (days)", "3")),
        "top": int(_ask("Max results", "5")),
    }
    print("\nquery JSON (save this to reuse):")
    print(json.dumps(query))
    print()
    return query


def main() -> None:
    # Load a local .env if python-dotenv is installed; harmless if it isn't.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    args = sys.argv[1:]
    show_links = "--links" in args
    args = [a for a in args if a != "--links"]
    if args and args[0] in ("-i", "--interactive"):
        query = prompt_query()
    elif args:
        with open(args[0], encoding="utf-8") as f:
            query = json.load(f)
        print(f"query: {args[0]}")
    else:
        query = CANONICAL_QUERY
        print("query: (canonical Uruguay -> Europe -> Tokyo -> home)")

    fetcher = choose_fetcher()
    _print_result(search_trip(query, fetcher), show_links)


if __name__ == "__main__":
    main()
