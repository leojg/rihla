# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
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

import urllib.parse
from datetime import date, datetime, timezone
from typing import Optional

from rihla.core import Quote
from rihla.fetchers._http import get_json

_BASE = "https://serpapi.com/search.json"


class SerpApiFetcher:
    name = "serpapi"

    def __init__(self, api_key: str, currency: str = "USD", timeout: int = 25):
        self.api_key, self.timeout = api_key, timeout
        self.currency = str(currency).strip().upper()   # google_flights wants ISO 4217 upper

    def parse_offer(self, raw: dict) -> Optional[Quote]:
        """Map one google_flights flight object to a Quote (real fare, so bookable=True).

        The airline/flight_number live on the itinerary's first segment. `link` stays None:
        SerpApi returns a `booking_token`, not a URL - resolving it is a second, quota-
        consuming call (deferred).
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("price"), (int, float)):
            return None
        segs = raw.get("flights") or []
        first = segs[0] if segs and isinstance(segs[0], dict) else {}
        return Quote(
            float(raw["price"]), self.name, bookable=True,
            # A live Google Flights quote: fetch time IS observation time.
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            airline=first.get("airline"),
            flight_number=first.get("flight_number"),
            link=None,
        )

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        params = {
            "engine": "google_flights",
            "departure_id": origin, "arrival_id": dest,
            "outbound_date": day.isoformat(), "type": "2",   # 2 = one-way
            "currency": self.currency, "api_key": self.api_key,
        }
        url = f"{_BASE}?{urllib.parse.urlencode(params)}"
        js = get_json(url, self.timeout) or {}
        flights = (js.get("best_flights") or []) + (js.get("other_flights") or [])
        quotes = [q for q in (self.parse_offer(f) for f in flights) if q is not None]
        return min(quotes, key=lambda q: q.price) if quotes else None
