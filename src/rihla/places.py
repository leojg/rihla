"""
places.py - predefined airport sets / regions and the canonical example trip.

Edit freely. EZE/AEP (Buenos Aires) are the key money-savers for intercontinental
departures from Uruguay - often far cheaper than MVD, a short hop/ferry away.

NOTE: regions are hardcoded here for v1. A general (MCP) tool will want these
exposed as schema enums, or resolved via a location-lookup API - see
docs/mcp-readiness.md.
"""
from __future__ import annotations

from datetime import date

from rihla.core import Place, Trip, linear_trip

MVD_AREA = Place("Montevideo / Buenos Aires", ("MVD", "EZE", "AEP"))
EUROPE   = Place("Europe", ("MAD", "BCN", "LIS", "CDG", "FCO", "AMS", "FRA"))
TOKYO    = Place("Tokyo", ("NRT", "HND"))


def example_trip() -> Trip:
    return linear_trip(
        name="Uruguay -> Europe (20-30d) -> Tokyo (15d) -> home",
        places=[MVD_AREA, EUROPE, TOKYO, MVD_AREA],
        first_earliest=date(2026, 9, 8),    # ~Sep 15, give it +/-7
        first_latest=date(2026, 9, 22),
        stays=[(20, 30), (15, 15)],         # Europe 20-30 nights, Japan exactly 15
        date_step=3,                         # every 3 days; lower = finer = more API calls
    )
