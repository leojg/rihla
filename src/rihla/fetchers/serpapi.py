"""
fetchers/serpapi.py - BYO-key real-data fill (DEV / SELF-HOST ONLY).

Queries Google Flights via SerpApi. Returns real, bookable fares (`bookable=True`), so it's
what completes the routes Travelpayouts' cache misses (verified 2026-06-28: every TP miss had
a real SerpApi fare). Per-date only - no calendar - so `fetch_leg` calls it on the sampled
candidate dates of routes the calendar source didn't cover.

DO NOT serve this from a public hosted instance: it scrapes Google, so redistributing its
results from a service you operate is a ToS/redistribution problem. It is a bring-your-own-key
fetcher for self-host and personal use, gated out of the `hosted` profile. The free tier is
250 searches/month - the binding personal-use budget, so let Travelpayouts carry covered
routes and keep `date_step` coarse.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from typing import Optional

from rihla.core import Quote

_BASE = "https://serpapi.com/search.json"


class SerpApiFetcher:
    name = "serpapi"

    def __init__(self, api_key: str, currency: str = "USD", timeout: int = 25):
        self.api_key, self.currency, self.timeout = api_key, currency, timeout

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        params = {
            "engine": "google_flights",
            "departure_id": origin, "arrival_id": dest,
            "outbound_date": day.isoformat(), "type": "2",   # 2 = one-way
            "currency": self.currency, "api_key": self.api_key,
        }
        url = f"{_BASE}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rihla/0.1"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                js = json.load(r)
        except Exception:                       # noqa: BLE001 - treat any failure as "no data"
            return None
        flights = (js.get("best_flights") or []) + (js.get("other_flights") or [])
        prices = [f["price"] for f in flights if isinstance(f.get("price"), (int, float))]
        return Quote(float(min(prices)), self.name, bookable=True) if prices else None
