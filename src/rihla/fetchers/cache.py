# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
fetchers/cache.py - in-process TTL cache for calendar month fetches.

`CalendarCacheFetcher` wraps a calendar-capable fetcher and memoizes
`quote_calendar(origin, dest, month)` for `ttl_seconds`. Empty months are cached too:
the repeated cache miss (an uncovered route re-probed on every search) is exactly the
quota waste this exists to stop. Per-date `quote()` delegates uncached. The wrapper
keeps the inner fetcher's `name`, so provenance still names the real source.

Only wrap calendar-capable fetchers: wrapping anything else would fabricate a
`quote_calendar` capability that the calendar-authoritative rule
(`base._calendar_exhaustive`) and `CompositeFetcher.quote_calendar` would trust.

Built for the long-running MCP server process: `time.monotonic` clock (immune to
wall-clock jumps; injectable for tests), a lock around the store (FastMCP may serve
tools concurrently), oldest-insertion eviction at `max_entries`. Stdlib only.
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Callable, Optional

from rihla.core import Quote


class CalendarCacheFetcher:
    def __init__(self, inner, ttl_seconds: float = 3600.0, max_entries: int = 1024,
                 clock: Callable[[], float] = time.monotonic):
        self.inner = inner
        self.name = inner.name
        # Mirror the inner source's currency so the `api.search_trip` guard sees through
        # the wrapper. The cache key stays (origin, dest, month): one instance serves ONE
        # currency, so per-currency separation is by instance (config builds one per).
        self.currency = getattr(inner, "currency", None)
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str, str], tuple[float, dict[date, Quote]]] = {}

    def quote(self, origin: str, dest: str, day: date) -> Optional[Quote]:
        return self.inner.quote(origin, dest, day)

    def quote_calendar(self, origin: str, dest: str, month: str) -> dict[date, Quote]:
        key = (origin, dest, month)
        now = self._clock()
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and now < hit[0]:
                return dict(hit[1])                # copy: callers can't poison the cache
        result = self.inner.quote_calendar(origin, dest, month)
        with self._lock:
            if key not in self._store and len(self._store) >= self._max:
                del self._store[next(iter(self._store))]   # dicts keep insertion order
            self._store[key] = (now + self._ttl, dict(result))
        return result
