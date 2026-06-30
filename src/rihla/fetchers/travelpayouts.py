"""
fetchers/travelpayouts.py - the shippable primary (free, redistribution-licensed).

Uses the Travelpayouts (Aviasales) cached **Data API** `prices_for_dates`. A whole-month
query returns the cheapest cached offers across the month in ONE call (the `quote_calendar`
path that collapses the call budget); a single-date query backs the per-date `quote()`.

Coverage = Aviasales search-history popularity, so prices are **indicative, not bookable**
(`bookable=False`) and thin routes can be missing entirely (verified 2026-06-28: strong on
EZE/AEP->Europe and Europe->Tokyo, empty on Tokyo->South America). The real-time Search API
has better coverage but is access-gated at >=50k MAU - unavailable here. Stdlib HTTP for
zero install; structurally correct per current docs, not exhaustively live-tested.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from typing import Optional

from rihla.core import Quote

_BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not isinstance(s, str) or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


class TravelpayoutsFetcher:
    name = "travelpayouts"

    def __init__(self, token: str, currency: str = "usd", timeout: int = 20):
        self.token, self.currency, self.timeout = token, currency, timeout

    def _prices_for_dates(self, origin: str, dest: str, departure_at: str, limit: int) -> list:
        params = {
            "origin": origin, "destination": dest,
            "departure_at": departure_at, "one_way": "true",
            "currency": self.currency, "sorting": "price", "limit": limit,
            "token": self.token,
        }
        url = f"{_BASE}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rihla/0.1"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                js = json.load(r)
        except Exception:                       # noqa: BLE001 - treat any failure as "no data"
            return []
        return js.get("data") or []

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        offers = self._prices_for_dates(origin, dest, day.isoformat(), limit=1)
        prices = [float(o["price"]) for o in offers if isinstance(o, dict) and "price" in o]
        return Quote(min(prices), self.name, bookable=False) if prices else None

    def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]:
        out: dict[date, Quote] = {}
        for o in self._prices_for_dates(origin, dest, month, limit=100):
            d = _parse_date(o.get("departure_at")) if isinstance(o, dict) else None
            p = o.get("price") if isinstance(o, dict) else None
            if d and isinstance(p, (int, float)) and (d not in out or p < out[d].price):
                out[d] = Quote(float(p), self.name, bookable=False)
        return out
