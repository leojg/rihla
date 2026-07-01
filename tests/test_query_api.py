"""
Tests for the query->result API: schema round-trip, multi-airport substitution, airline
surfacing, and the honest no-answer statuses (partial / no_coverage / constraints).
Runnable via pytest OR standalone: `python tests/test_query_api.py`.
"""
from datetime import date

from rihla.api import Query, assemble_result, search_trip
from rihla.core import Gap, Leg, Place, PricedLeg, Quote, Trip
from rihla.fetchers import MockFetcher, SerpApiFetcher, TravelpayoutsFetcher


CANONICAL = {
    "origins": ["MVD", "EZE", "AEP"],
    "stops": ["EUROPE", ["NRT", "HND"], "MVD_AREA"],
    "earliest": "2026-09-08",
    "latest": "2026-09-22",
    "stays": [[20, 30], [15, 15]],
    "date_step": 3,
    "top": 5,
}


# --- test doubles -----------------------------------------------------------

class NoneFetcher:
    """Prices nothing - to exercise no_coverage."""
    name = "none"

    def quote(self, origin, dest, day):
        return None


class BlockDestFetcher:
    """MockFetcher, but returns nothing for routes into a blocked destination set."""
    name = "blockdest"

    def __init__(self, blocked):
        self._m = MockFetcher()
        self._blocked = set(blocked)

    def quote(self, origin, dest, day):
        return None if dest in self._blocked else self._m.quote(origin, dest, day)


class FixedFetcher:
    """Fixed price per (origin, dest) pair, regardless of date - for deterministic asserts."""
    name = "fixed"

    def __init__(self, prices):
        self._p = prices

    def quote(self, origin, dest, day):
        p = self._p.get((origin, dest))
        return Quote(p, self.name, bookable=True, airline="XX") if p is not None else None


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


# --- tests ------------------------------------------------------------------

def test_query_round_trip():
    q = Query.from_dict(CANONICAL)
    assert Query.from_dict(q.to_dict()) == q


def test_query_rejects_malformed():
    assert _raises(lambda: Query.from_dict({**CANONICAL, "stays": []}))       # len mismatch
    assert _raises(lambda: Query.from_dict({**CANONICAL, "origins": []}))     # no origin
    assert _raises(lambda: Query.from_dict({**CANONICAL, "earliest": "nope"}))  # bad date
    assert _raises(lambda: Query.from_dict({**CANONICAL, "surprise": 1}))     # unknown field
    assert _raises(lambda: Query.from_dict({"stops": ["EUROPE"]}))            # missing fields


def test_multi_airport_picks_cheapest_airport():
    # single leg, two candidate origins; EZE is the cheaper origin -> it must win.
    q = {"origins": ["MVD", "EZE"], "stops": [["MAD"]], "earliest": "2026-09-08",
         "latest": "2026-09-14", "stays": [], "date_step": 3}
    res = search_trip(q, FixedFetcher({("MVD", "MAD"): 900.0, ("EZE", "MAD"): 600.0}))
    assert res["status"] == "ok"
    assert res["options"][0]["legs"][0]["from"] == "EZE"
    assert res["options"][0]["total"] == 600.0


def test_exact_and_range_stays_yield_complete_options():
    res = search_trip(CANONICAL, MockFetcher())
    assert res["status"] == "ok"
    top = res["options"][0]
    assert top["complete"] is True and top["duration_days"] is not None
    # options are price-ranked
    totals = [o["total"] for o in res["options"]]
    assert totals == sorted(totals)


def test_airline_surfaced_on_every_leg():
    res = search_trip(CANONICAL, MockFetcher())
    for opt in res["options"]:
        for leg in opt["legs"]:
            assert leg["airline"] and leg["source"] == "mock"


def test_partial_when_a_leg_is_uncovered():
    # block Europe->Japan (leg2) -> a partial over leg1 + leg3.
    res = search_trip(CANONICAL, BlockDestFetcher(blocked={"NRT", "HND"}))
    assert res["status"] == "partial"
    assert res["missing_legs"] == ["leg2"]
    assert res["options"], "should still return the legs that were priced"
    for opt in res["options"]:
        assert opt["complete"] is False
        assert opt["duration_days"] is None            # partial spans a missing middle leg
        assert [pl["leg"] for pl in opt["legs"]] == ["leg1", "leg3"]


def test_partial_enforces_surviving_gap_when_end_leg_missing():
    # block Tokyo->home (leg3) -> covered [leg1, leg2]; the leg1->leg2 (20-30d) gap survives
    # and must still be enforced (unlike the middle-leg case where both gaps drop).
    res = search_trip(CANONICAL, BlockDestFetcher(blocked={"MVD", "EZE", "AEP"}))
    assert res["status"] == "partial"
    assert res["missing_legs"] == ["leg3"]
    assert res["options"]
    for opt in res["options"]:
        legs = {pl["leg"]: date.fromisoformat(pl["date"]) for pl in opt["legs"]}
        assert set(legs) == {"leg1", "leg2"}
        assert 20 <= (legs["leg2"] - legs["leg1"]).days <= 30   # surviving gap enforced


def test_no_coverage_when_nothing_prices():
    res = search_trip(CANONICAL, NoneFetcher())
    assert res["status"] == "no_coverage"
    assert res["options"] == []
    assert res["missing_legs"] == ["leg1", "leg2", "leg3"]


def test_constraints_unsatisfiable_unit():
    # All legs priced, but the only dates are 1 day apart while the gap needs >= 10.
    # Unreachable through a linear Query (windows are derived), so test assemble_result directly.
    A, B = Place("A", ("AAA",)), Place("B", ("BBB",))
    trip = Trip("t", [Leg("leg1", A, B, date(2026, 9, 1), date(2026, 9, 1)),
                      Leg("leg2", B, A, date(2026, 9, 2), date(2026, 9, 2))],
                [Gap("leg1", "leg2", min_days=10)])
    grid = {
        "leg1": {date(2026, 9, 1): PricedLeg("leg1", date(2026, 9, 1), "AAA", "BBB", 100.0, "x")},
        "leg2": {date(2026, 9, 2): PricedLeg("leg2", date(2026, 9, 2), "BBB", "AAA", 100.0, "x")},
    }
    res = assemble_result(trip, grid)
    assert res["status"] == "constraints_unsatisfiable"
    assert res["missing_legs"] == [] and res["options"] == []


def test_parse_offer_travelpayouts():
    f = TravelpayoutsFetcher("tok")
    q = f.parse_offer({"price": 500, "airline": "IB", "flight_number": 6842,
                       "link": "/search/MVD0809MAD1"})
    assert q.price == 500.0 and q.source == "travelpayouts" and q.bookable is False
    assert q.airline == "IB" and q.flight_number == "6842"
    assert q.link == "https://www.aviasales.com/search/MVD0809MAD1"
    assert f.parse_offer({"airline": "IB"}) is None            # no price -> no quote


def test_parse_offer_serpapi():
    f = SerpApiFetcher("key")
    q = f.parse_offer({"price": 780, "booking_token": "xyz",
                       "flights": [{"airline": "Iberia", "flight_number": "IB 6842"}]})
    assert q.price == 780.0 and q.source == "serpapi" and q.bookable is True
    assert q.airline == "Iberia" and q.flight_number == "IB 6842"
    assert q.link is None                                       # booking_token != URL (deferred)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} passed")
