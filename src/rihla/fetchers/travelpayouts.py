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

import urllib.parse
from datetime import date
from typing import Optional

from rihla.core import Quote
from rihla.fetchers._http import get_json

_BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
_AVIASALES = "https://www.aviasales.com"     # v3 `link` is a relative path off this host


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
        js = get_json(url, self.timeout) or {}
        return js.get("data") or []

    def parse_offer(self, raw: dict) -> Optional[Quote]:
        """Map one `prices_for_dates` offer to a Quote (indicative/cached, so bookable=False)."""
        if not isinstance(raw, dict) or not isinstance(raw.get("price"), (int, float)):
            return None
        link = raw.get("link")
        fn = raw.get("flight_number")
        return Quote(
            float(raw["price"]), self.name, bookable=False,
            airline=raw.get("airline"),
            flight_number=str(fn) if fn is not None else None,
            link=f"{_AVIASALES}{link}" if isinstance(link, str) and link.startswith("/") else link,
        )

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        offers = self._prices_for_dates(origin, dest, day.isoformat(), limit=1)
        quotes = [q for q in (self.parse_offer(o) for o in offers) if q is not None]
        return min(quotes, key=lambda q: q.price) if quotes else None

    def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]:
        out: dict[date, Quote] = {}
        for o in self._prices_for_dates(origin, dest, month, limit=100):
            q = self.parse_offer(o)
            d = _parse_date(o.get("departure_at")) if isinstance(o, dict) else None
            if q is not None and d is not None and (d not in out or q.price < out[d].price):
                out[d] = q
        return out
