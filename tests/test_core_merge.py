"""
Tests for the pure optimizer and the multi-source merge policy.
Runnable via pytest OR standalone: `python tests/test_core_merge.py`.
"""
from datetime import date

from rihla.core import Place, PricedLeg, Quote, linear_trip, optimize
from rihla.fetchers import MockFetcher, build_grid, fetch_leg, merge_quotes


def _trip():
    A = Place("A", ("AAA", "BBB"))
    B = Place("B", ("CCC",))
    C = Place("C", ("DDD",))
    return linear_trip("t", [A, B, C], date(2026, 9, 1), date(2026, 9, 9),
                       stays=[(5, 10)], date_step=3)


def test_merge_prefers_bookable_over_cheaper_cached():
    cached_cheap = Quote(100.0, "travelpayouts", bookable=False)
    real_dearer = Quote(150.0, "serpapi", bookable=True)
    assert merge_quotes([cached_cheap, real_dearer]) is real_dearer


def test_merge_falls_back_to_cheapest_cached_when_no_bookable():
    a = Quote(200.0, "travelpayouts", bookable=False)
    b = Quote(120.0, "mock", bookable=False)
    assert merge_quotes([a, b]) is b


def test_merge_empty_is_none():
    assert merge_quotes([None, None]) is None


def test_merge_preserves_winning_quote_metadata():
    real = Quote(150.0, "serpapi", bookable=True, airline="Iberia", flight_number="IB6842")
    cached = Quote(100.0, "travelpayouts", bookable=False, airline="IB")
    won = merge_quotes([cached, real])                 # bookable wins over cheaper cached
    assert won is real and won.airline == "Iberia" and won.flight_number == "IB6842"


def test_optimize_offline_returns_ranked_bundles_with_source():
    trip = _trip()
    best = optimize(trip, build_grid(MockFetcher(), trip), top=5)
    assert best, "mock should price every leg"
    totals = [b.total for b in best]
    assert totals == sorted(totals), "bundles ranked cheapest-first"
    assert all(p.source == "mock" for b in best for p in b.chosen.values())


def test_fetch_leg_per_date_fallback_when_no_calendar():
    leg = _trip().legs[0]                      # MockFetcher has no quote_calendar
    grid = fetch_leg(MockFetcher(), leg)
    assert grid and all(isinstance(p, PricedLeg) for p in grid.values())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} passed")
