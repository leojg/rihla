# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
mcp_server.py - the local stdio MCP server: two tools, resolve then search.

The two-tool protocol (ADR-0004): the client agent proposes IATA codes for the
traveler's named places and calls `resolve_airports` (cheap, quota-free) to validate
and enrich them; it presents the result - nearby alternatives included - and only
after the traveler confirms does it call `search_trip` (the priced, quota-limited
call). The ordering is enforced by the tool descriptions; both tools are honest reads
(`readOnlyHint`), so no protocol-level gate is needed.

Over stdio, stdout IS the JSON-RPC stream - anything human-readable (the fetcher
selection banner) goes to stderr.

Run: python -m rihla.mcp_server   (or the `rihla-mcp` script; stdio transport)
"""
from __future__ import annotations

import sys
import threading

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from rihla.api import Query, search_trip as _search_trip
from rihla.config import build_fetcher
from rihla.fetchers import PriceFetcher
from rihla.places import REGIONS
from rihla.resolve import resolve_places

# Load a local .env if python-dotenv is installed (same convenience as the CLI):
# MCP clients rarely pass provider keys through their env config.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# One fetcher per currency: a fetcher serves the single currency it was built for, and
# per-currency instances keep each calendar cache single-currency (its key carries no
# currency). Lazy under a lock - FastMCP may serve tools concurrently.
_FETCHERS: dict[str, PriceFetcher] = {}
_FETCHERS_LOCK = threading.Lock()


def _fetcher_for(currency: str) -> PriceFetcher:
    with _FETCHERS_LOCK:
        fetcher = _FETCHERS.get(currency)
        if fetcher is None:
            fetcher, notes = build_fetcher(currency=currency)
            for note in notes:
                print(note, file=sys.stderr)
            _FETCHERS[currency] = fetcher
    return fetcher


# Eager default build: the selection banner belongs at server start, not first search.
_fetcher_for("USD")

mcp = FastMCP(
    "rihla",
    instructions=(
        "Flight search for flexible multi-leg, multi-airport trips. Workflow: "
        "1) resolve_airports to validate the codes you propose (cheap, quota-free); "
        "2) present the validated airports - nearby alternatives included - and get "
        "the traveler's explicit confirmation; 3) search_trip (quota-limited)."
    ),
)


class PlaceProposal(BaseModel):
    """One place the traveler named, with the IATA codes the agent proposes for it."""
    role: str = Field(
        description="Where this place sits in the trip, e.g. 'origin', 'stop 1', 'final'.")
    query: str = Field(
        description="The traveler's own words for the place, e.g. 'montevideo'.")
    primary: list[str] = Field(
        description="IATA codes directly serving the place, e.g. montevideo -> ['MVD'].")
    nearby: list[str] = Field(
        default_factory=list,
        description="A BOUNDED set of nearby alternative airports worth pricing, "
                    "e.g. for Montevideo: ['EZE', 'AEP'] (Buenos Aires).")


class SearchQuery(BaseModel):
    """Mirror of `rihla.api.Query`, published as the tool's input schema.

    Purely declarative: the handler feeds `model_dump()` to `api.Query.from_dict`,
    which stays the single validator of record.
    """
    origins: list[str] = Field(
        description="Origin airports as validated 3-letter IATA codes, "
                    "e.g. ['MVD', 'EZE', 'AEP'].")
    stops: list[str | list[str]] = Field(
        description=f"Ordered destinations after the origin. Each stop is a region "
                    f"name ({', '.join(sorted(REGIONS))}) or a list of validated IATA "
                    f"codes. For a roundtrip, append the origin list again as the "
                    f"final stop.")
    earliest: str = Field(description="First-departure window start (ISO, YYYY-MM-DD).")
    latest: str = Field(description="First-departure window end (ISO, YYYY-MM-DD).")
    stays: list[tuple[int, int]] = Field(
        description="[min, max] nights at each intermediate stop; "
                    "len(stays) == len(stops) - 1.")
    date_step: int = Field(
        default=3, description="Sample departures every N days; lower = more API calls.")
    top: int = Field(default=5, description="Max itineraries to return.")
    currency: str = Field(
        default="USD",
        description="ISO 4217 code, e.g. 'USD', 'EUR'. Prices are fetched in this currency.")
    adults: int = 1


_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


@mcp.tool(
    annotations=_READ_ONLY,
    description=(
        "Validate and enrich proposed IATA airport codes for the traveler's named "
        "places. Cheap and quota-free - ALWAYS call this first. You propose the codes: "
        "parse the traveler's words and give each place's `primary` codes plus a "
        "BOUNDED `nearby` set of alternative airports worth pricing - in particular, "
        "for Montevideo (MVD) also propose Buenos Aires EZE and AEP (a short "
        "ferry/hop away and routinely far cheaper than MVD); for a broad region like "
        "'Europe' propose a handful of major gateways (e.g. MAD, BCN, LIS, CDG, FCO, "
        "AMS, FRA), not an exhaustive list. Codes that fail validation come back in "
        "`unresolved` - never pass those to search_trip. Present the validated "
        "airports (nearby alternatives included) to the traveler and get explicit "
        "confirmation BEFORE calling search_trip."
    ),
)
def resolve_airports(places: list[PlaceProposal]) -> dict:
    return resolve_places([p.model_dump() for p in places])


@mcp.tool(
    annotations=_READ_ONLY,
    description=(
        "Search flight prices for a flexible multi-leg trip and return ranked "
        "itineraries. QUOTA-LIMITED: only call after resolve_airports validated the "
        "codes AND the traveler explicitly confirmed the airport set - never call "
        "speculatively. Statuses: ok | partial | no_coverage | "
        "constraints_unsatisfiable (missing_legs names any unpriced legs). On "
        "incomplete options `total` is null - quote `priced_total` as the subtotal of "
        "the priced legs only, never as a trip price. `hints` lists cached fares just "
        "OUTSIDE the departure window for each unpriced leg: offer the traveler a "
        "window shift instead of retrying blind (re-searching the same window, or "
        "lowering date_step, cannot find more). `sources` names the data sources "
        "consulted; per-leg `fetched_at` says when a cached fare was observed."
    ),
)
def search_trip(query: SearchQuery) -> dict:
    # Validate first (Query stays the validator of record) so a bad currency errors
    # before it can build a fetcher for it.
    q = Query.from_dict(query.model_dump())
    return _search_trip(q, _fetcher_for(q.currency))


def main() -> None:
    mcp.run()                                # stdio transport by default


if __name__ == "__main__":
    main()
