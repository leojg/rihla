#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
scripts/probe_coverage.py - THROWAWAY coverage probe (NOT part of the rihla package).

The gating experiment for the data-layer pivot (see
docs/spec.md / ~/Dev/specs/rihla-respec-multiprovider-opencore.md, Phase 1 Step 1):

  Does Travelpayouts actually return fares for the canonical Rihla routes - especially
  the low-traffic MVD/EZE origins - or is its search-traffic-derived cache sparse
  exactly where it matters?

Travelpayouts is the SUBJECT. SerpApi (Google Flights) is an OPTIONAL real-data
baseline that runs ONLY on Travelpayouts misses (to conserve the 250/mo free tier),
so an empty Travelpayouts cell can be classified as "no such route" vs "cache miss,
a real fare exists". The second case is the MVD-coverage risk made visible.

Run:
  # put TRAVELPAYOUTS_TOKEN (and optionally SERPAPI_KEY) in .env, then:
  python scripts/probe_coverage.py

Stdlib only (+ python-dotenv if present) so it runs with zero install. Endpoints are
structurally correct per current Travelpayouts/SerpApi docs but NOT live-tested here -
if cells look wrong, verify params/response shape against the live API consoles.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TP_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
SERP_KEY = os.getenv("SERPAPI_KEY")

CURRENCY = "usd"
HTTP_TIMEOUT = 20

# --- canonical routes (spec ss4) -------------------------------------------
MVD_AREA = ("MVD", "EZE", "AEP")
EUROPE = ("MAD", "BCN", "LIS", "CDG", "FCO", "AMS", "FRA")
TOKYO = ("NRT", "HND")


@dataclass
class Leg:
    name: str
    origins: tuple[str, ...]
    dests: tuple[str, ...]
    tp_month: str       # YYYY-MM - Travelpayouts whole-month coverage check
    serp_date: str      # YYYY-MM-DD - representative date for the SerpApi baseline


LEGS = [
    Leg("L1  MVD-area -> Europe", MVD_AREA, EUROPE, "2026-09", "2026-09-15"),
    Leg("L2  Europe -> Tokyo", EUROPE, TOKYO, "2026-10", "2026-10-10"),
    Leg("L3  Tokyo -> MVD-area", TOKYO, MVD_AREA, "2026-10", "2026-10-25"),
]


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rihla-probe/0.1"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.load(r)
    except Exception as e:                       # noqa: BLE001 - probe: surface, don't crash
        return {"_error": str(e)}


def tp_cheapest(origin: str, dest: str, month: str) -> tuple[float | None, str]:
    """Cheapest one-way fare for a route in a month via Travelpayouts v3 prices_for_dates."""
    if not TP_TOKEN:
        return None, "no token"
    params = {
        "origin": origin, "destination": dest,
        "departure_at": month, "one_way": "true",
        "currency": CURRENCY, "sorting": "price", "limit": 1,
        "token": TP_TOKEN,
    }
    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + urllib.parse.urlencode(params)
    js = _get_json(url) or {}
    if "_error" in js:
        return None, f"err: {js['_error']}"
    data = js.get("data") or []
    prices = [float(o["price"]) for o in data if isinstance(o, dict) and "price" in o]
    return (min(prices), "ok") if prices else (None, "empty")


def serp_cheapest(origin: str, dest: str, date: str) -> tuple[float | None, str]:
    """Cheapest one-way Google Flights fare on a date via SerpApi (baseline only)."""
    if not SERP_KEY:
        return None, "-"
    params = {
        "engine": "google_flights",
        "departure_id": origin, "arrival_id": dest,
        "outbound_date": date, "type": "2",      # 2 = one-way
        "currency": "USD", "api_key": SERP_KEY,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    js = _get_json(url) or {}
    if "_error" in js:
        return None, f"err: {js['_error']}"
    flights = (js.get("best_flights") or []) + (js.get("other_flights") or [])
    prices = [f["price"] for f in flights if isinstance(f.get("price"), (int, float))]
    return (float(min(prices)), "ok") if prices else (None, "empty")


def main() -> int:
    if not TP_TOKEN:
        print("WARNING: TRAVELPAYOUTS_TOKEN not set - that's the whole point of this probe.")
        print("         Add it to .env (and optionally SERPAPI_KEY), then re-run.\n")
    baseline = "ON" if SERP_KEY else "OFF (set SERPAPI_KEY to classify TP misses)"
    print(f"Rihla coverage probe - Travelpayouts (subject) | SerpApi baseline: {baseline}\n")

    tp_hits = tp_total = 0
    real_fare_on_tp_miss = 0
    for leg in LEGS:
        print(f"== {leg.name}   (TP month {leg.tp_month} | baseline date {leg.serp_date})")
        print(f"   {'route':<12}{'Travelpayouts':>16}   baseline")
        for o in leg.origins:
            for d in leg.dests:
                tp_total += 1
                tp_price, tp_note = tp_cheapest(o, d, leg.tp_month)
                if tp_price is not None:
                    tp_hits += 1
                    tp_cell = f"${tp_price:,.0f}"
                    base_cell = ""                # only baseline the misses
                else:
                    tp_cell = f"-  ({tp_note})"
                    sp_price, sp_note = serp_cheapest(o, d, leg.serp_date) if SERP_KEY else (None, "-")
                    if sp_price is not None:
                        real_fare_on_tp_miss += 1
                        base_cell = f"real ${sp_price:,.0f}  <-- TP MISS, fare exists"
                    elif SERP_KEY:
                        base_cell = f"none ({sp_note}) - likely no route"
                    else:
                        base_cell = ""
                print(f"   {o}->{d:<8}{tp_cell:>16}   {base_cell}")
        print()

    pct = (100 * tp_hits / tp_total) if tp_total else 0
    print(f"Travelpayouts coverage: {tp_hits}/{tp_total} routes ({pct:.0f}%).")
    if SERP_KEY:
        print(f"TP misses where a real fare exists: {real_fare_on_tp_miss} "
              f"(these are cache gaps, not dead routes - the MVD risk).")
    print()
    print("GATE: if the MVD/EZE origin rows (L1) and dest rows (L3) are mostly '-', "
          "Travelpayouts is NOT a safe hosted primary for those origins - fall back to "
          "SerpApi BYOK on self-host and/or lean on EZE over MVD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
