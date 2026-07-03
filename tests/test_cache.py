# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
Tests for the calendar TTL cache (fetchers/cache.py) and its config wiring.
Runnable via pytest OR standalone: `python tests/test_cache.py`.
"""
from datetime import date

from rihla.config import build_fetcher
from rihla.core import Quote
from rihla.fetchers import CalendarCacheFetcher, TravelpayoutsFetcher


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CountingCalendar:
    """Calendar source that counts upstream calls."""
    name = "counting"

    def __init__(self, data=None):
        self.calls = 0
        self._data = {date(2026, 9, 1): Quote(100.0, "counting")} if data is None else data

    def quote(self, origin, dest, day):
        return None

    def quote_calendar(self, origin, dest, month):
        self.calls += 1
        return dict(self._data)


def _cached(inner=None, ttl=60.0, **kw):
    clock = FakeClock()
    return CalendarCacheFetcher(inner or CountingCalendar(), ttl_seconds=ttl,
                                clock=clock, **kw), clock


def test_hit_within_ttl_and_refetch_after_expiry():
    f, clock = _cached()
    first = f.quote_calendar("AAA", "BBB", "2026-09")
    assert f.quote_calendar("AAA", "BBB", "2026-09") == first
    assert f.inner.calls == 1
    clock.now += 61
    f.quote_calendar("AAA", "BBB", "2026-09")
    assert f.inner.calls == 2


def test_empty_months_are_cached_too():
    # The repeated cache miss (an uncovered route re-probed every search) is exactly
    # the quota waste the cache exists to stop.
    f, _ = _cached(CountingCalendar(data={}))
    assert f.quote_calendar("AAA", "BBB", "2026-09") == {}
    f.quote_calendar("AAA", "BBB", "2026-09")
    assert f.inner.calls == 1


def test_keys_are_independent():
    f, _ = _cached()
    f.quote_calendar("AAA", "BBB", "2026-09")
    f.quote_calendar("AAA", "BBB", "2026-10")
    f.quote_calendar("AAA", "CCC", "2026-09")
    assert f.inner.calls == 3


def test_hits_return_copies():
    f, _ = _cached()
    stolen = f.quote_calendar("AAA", "BBB", "2026-09")
    stolen.clear()                                 # a caller mutating its result...
    assert f.quote_calendar("AAA", "BBB", "2026-09")   # ...can't poison the cache
    assert f.inner.calls == 1


def test_eviction_at_max_entries():
    f, _ = _cached(max_entries=2)
    f.quote_calendar("AAA", "BBB", "2026-09")
    f.quote_calendar("AAA", "BBB", "2026-10")
    f.quote_calendar("AAA", "BBB", "2026-11")      # evicts 2026-09 (oldest insertion)
    f.quote_calendar("AAA", "BBB", "2026-10")      # still cached
    f.quote_calendar("AAA", "BBB", "2026-09")      # gone -> refetched
    assert f.inner.calls == 4


def test_name_and_quote_delegate_to_inner():
    f, _ = _cached()
    assert f.name == "counting"                    # provenance names the real source
    assert f.quote("AAA", "BBB", date(2026, 9, 1)) is None


def test_build_fetcher_wraps_travelpayouts_by_default():
    fetcher, notes = build_fetcher({"TRAVELPAYOUTS_TOKEN": "tok"})
    assert isinstance(fetcher, CalendarCacheFetcher)
    assert fetcher.name == "travelpayouts"
    assert isinstance(fetcher.inner, TravelpayoutsFetcher)
    assert any("calendar cache" in n for n in notes)


def test_build_fetcher_ttl_zero_disables_cache():
    fetcher, _ = build_fetcher({"TRAVELPAYOUTS_TOKEN": "tok", "RIHLA_CALENDAR_TTL": "0"})
    assert isinstance(fetcher, TravelpayoutsFetcher)


def test_build_fetcher_threads_currency_to_every_source():
    # Each source normalizes to its own wire case; the cache wrapper mirrors its inner
    # source (one instance = one currency, so the cache key needs no currency component);
    # the composite reports the agreed currency canonically.
    fetcher, _ = build_fetcher({"TRAVELPAYOUTS_TOKEN": "tok", "SERPAPI_KEY": "k"},
                               currency="eur")
    tp, sp = fetcher.fetchers
    assert tp.currency == "eur" and tp.inner.currency == "eur"
    assert sp.currency == "EUR"
    assert fetcher.currency == "EUR"


def test_build_fetcher_defaults_to_usd():
    fetcher, _ = build_fetcher({"TRAVELPAYOUTS_TOKEN": "tok"})
    assert fetcher.currency == "usd"               # mirrored from travelpayouts wire format


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} passed")
