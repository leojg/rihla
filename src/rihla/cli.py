# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
cli.py - run a query from the command line.

The only layer that does user-facing I/O (reading env / a query file / printing). Keeping
print() out of core/fetchers/api matters: an MCP server over stdio would have its transport
corrupted by stray stdout. This is a thin adapter over `search_trip` - the same seam the
future MCP server wraps.

Usage:
  rihla [query.json] [--links]     # no arg -> the canonical Uruguay->Europe->Tokyo trip
  rihla -i                         # build the query interactively
"""
from __future__ import annotations

import argparse
import json

from rihla import __version__
from rihla.api import search_trip
from rihla.config import build_fetcher
from rihla.fetchers import PriceFetcher
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


def choose_fetcher(currency: str = "USD") -> PriceFetcher:
    """Build the data source from the environment and print the selection banner.

    Selection logic lives in `config.build_fetcher` (print-free, so the MCP server can
    share it); this wrapper is just the CLI's rendering of the notes.
    """
    fetcher, notes = build_fetcher(currency=currency)
    for note in notes:
        print(note)
    print()
    return fetcher


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


def _print_hints(res: dict, show_links: bool = False) -> None:
    """Nearest cached fares just outside the departure window, per unpriced leg."""
    hints = res.get("hints") or {}
    if not any(hints.values()):
        return
    print("Nearest fares OUTSIDE the departure window (shift/widen dates to catch these):")
    for leg_name, entries in hints.items():
        print(f"  {leg_name}:")
        for h in entries:
            print("     " + _fmt_leg(h, show_links))
    print()


def _print_result(res: dict, show_links: bool = False) -> None:
    status = res["status"]
    if status == "no_coverage":
        legs = ", ".join(res["missing_legs"])
        print(f"No prices found for any leg ({legs}). Widen the windows, add a source "
              "(e.g. SERPAPI_KEY for thin routes like Tokyo->South America), or check coverage.")
        _print_hints(res, show_links)
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
        # `total` is null unless complete (ADR-0005) - a partial shows its priced subtotal.
        amount = opt["total"] if opt["complete"] else opt["priced_total"]
        meta = (f"{opt['duration_days']} days door-to-door" if opt["complete"]
                else f"partial: {len(opt['legs'])} of {total_legs} legs - priced legs only")
        print(f"{i}. {amount:,.0f} {opt['currency']}   ({meta})")
        for leg in opt["legs"]:
            print("     " + _fmt_leg(leg, show_links))
        print()
    _print_hints(res, show_links)
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
    parser = argparse.ArgumentParser(
        prog="rihla",
        description="Flexible multi-leg, multi-airport flight search - cheapest "
                    "combinations across the whole itinerary.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("query_file", nargs="?", metavar="query.json",
                        help="query file to run (default: the canonical demo trip)")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="build the query interactively instead of from a file")
    parser.add_argument("--links", action="store_true", help="show booking links")
    args = parser.parse_args()

    # Load a local .env if python-dotenv is installed; harmless if it isn't.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.interactive:
        query = prompt_query()
    elif args.query_file:
        try:
            with open(args.query_file, encoding="utf-8") as f:
                query = json.load(f)
        except FileNotFoundError:
            parser.error(f"query file not found: {args.query_file}")
        print(f"query: {args.query_file}")
    else:
        query = CANONICAL_QUERY
        print("query: (canonical Uruguay -> Europe -> Tokyo -> home)")

    fetcher = choose_fetcher(query.get("currency", "USD"))
    _print_result(search_trip(query, fetcher), show_links=args.links)


if __name__ == "__main__":
    main()
