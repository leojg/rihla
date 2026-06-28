"""
fetchers/amadeus.py - live fetcher over the Amadeus Self-Service API + sqlite cache.

Free tier ~2,000 searches/month. LCCs and (currently) AA/DL/BA are excluded, so
cross-check thin routes elsewhere. Verify exact param/field names against current
Amadeus docs - structurally correct here, not live-tested.

The local sqlite cache (keyed origin/dest/day/adults/ccy with a TTL) makes reruns
nearly free, and negative-caches dead routes as -1 so they aren't re-hit within the
TTL. When a second source (e.g. Travelpayouts) is added, this cache is the natural
piece to extract into a shared module.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Optional


class AmadeusFetcher:
    """Amadeus Self-Service flight search + local sqlite price cache."""
    def __init__(self, client_id: str, client_secret: str,
                 adults: int = 1, currency: str = "USD",
                 cache_path: str = "flight_cache.db", cache_ttl_hours: int = 24):
        from amadeus import Client          # pip install amadeus
        self.api = Client(client_id=client_id, client_secret=client_secret)
        self.adults, self.currency, self.ttl = adults, currency, cache_ttl_hours
        self.db = sqlite3.connect(cache_path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS prices(
            origin TEXT, dest TEXT, day TEXT, adults INT, ccy TEXT,
            price REAL, fetched_at TEXT,
            PRIMARY KEY (origin, dest, day, adults, ccy))""")

    def _cached(self, origin: str, dest: str, day: date) -> Optional[float]:
        row = self.db.execute(
            "SELECT price, fetched_at FROM prices "
            "WHERE origin=? AND dest=? AND day=? AND adults=? AND ccy=?",
            (origin, dest, day.isoformat(), self.adults, self.currency)).fetchone()
        if not row:
            return None
        price, fetched = row
        # NOTE: datetime.utcnow() is deprecated on 3.12+; revisit (timezone-aware)
        # when modernizing - left as-is here to keep this pass behavior-preserving.
        age_h = (datetime.utcnow() - datetime.fromisoformat(fetched)).total_seconds() / 3600
        return price if age_h < self.ttl else None

    def price(self, origin: str, dest: str, day: date) -> Optional[float]:
        hit = self._cached(origin, dest, day)
        if hit is not None:                 # -1 is cached "no offer", avoids re-hitting dead routes
            return hit if hit >= 0 else None
        from amadeus import ResponseError
        try:
            resp = self.api.shopping.flight_offers_search.get(
                originLocationCode=origin, destinationLocationCode=dest,
                departureDate=day.isoformat(), adults=self.adults,
                currencyCode=self.currency, max=1)
            offers = resp.data
            price = min(float(o["price"]["grandTotal"]) for o in offers) if offers else -1.0
        except ResponseError:
            price = -1.0
        self.db.execute("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)",
                        (origin, dest, day.isoformat(), self.adults, self.currency,
                         price, datetime.utcnow().isoformat()))
        self.db.commit()
        return price if price >= 0 else None
