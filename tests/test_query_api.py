# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
Tests for the query->result API: schema round-trip, multi-airport substitution, airline
surfacing, the honest no-answer statuses (partial / no_coverage / constraints), and the
ADR-0005 transparency fields (null partial totals, hints, sources, fetched_at).
Runnable via pytest OR standalone: `python tests/test_query_api.py`.
"""
from datetime import date

from rihla.api import Query, assemble_result, search_trip
from rihla.core import Gap, Leg, Place, PricedLeg, Quote, Trip
from rihla.fetchers import CompositeFetcher, MockFetcher, SerpApiFetcher, TravelpayoutsFetcher


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


class CalendarOnlyFetcher:
    """Calendar-capable double; per-date quote() must never be called on it, proving the
    empty calendar is treated as authoritative when it is the only source (ADR-0005)."""
    name = "calonly"

    def __init__(self, calendars):                 # {(origin, dest): {date: price}}
        self._c = calendars

    def quote(self, origin, dest, day):
        raise AssertionError("per-date quote() called on a calendar-only source")

    def quote_calendar(self, origin, dest, month):
        return {d: Quote(p, self.name, bookable=False, airline="XX", fetched_at="2026-07-01")
                for d, p in self._c.get((origin, dest), {}).items()
                if d.isoformat()[:7] == month}


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


def test_query_rejects_non_iata_codes():
    # a city name slipped in as a "code" must fail loudly at construction, not surface
    # later as a misleading no_coverage (ADR-0004).
    assert _raises(lambda: Query.from_dict({**CANONICAL, "origins": ["MONTEVIDEO"]}))
    assert _raises(lambda: Query.from_dict(
        {**CANONICAL, "stops": ["EUROPE", ["NARITA", "HND"], "MVD_AREA"]}))
    # region-name stops (str) are exempt - they resolve via places.REGIONS.
    q = Query.from_dict(CANONICAL)
    assert q.stops[0] == "EUROPE" and q.stops[2] == "MVD_AREA"


def test_query_normalizes_and_validates_currency():
    assert Query.from_dict({**CANONICAL, "currency": "eur"}).currency == "EUR"
    assert _raises(lambda: Query.from_dict({**CANONICAL, "currency": "euros"}))
    assert _raises(lambda: Query.from_dict({**CANONICAL, "currency": ""}))


def test_search_trip_rejects_currency_the_fetcher_does_not_serve():
    # A fetcher serves the one currency it was built for; a query asking for another must
    # fail loudly - the silent path labels one currency's prices with another's code.
    fetcher = TravelpayoutsFetcher("tok", currency="usd")
    assert _raises(lambda: search_trip({**CANONICAL, "currency": "EUR"}, fetcher))


def test_search_trip_accepts_matching_fetcher_currency_case_insensitively():
    q = {"origins": ["MVD"], "stops": [["MAD"]], "earliest": "2026-09-08",
         "latest": "2026-09-14", "stays": [], "currency": "eur"}
    fetcher = FixedFetcher({("MVD", "MAD"): 500.0})
    fetcher.currency = "eur"                       # sources declare their own wire case
    res = search_trip(q, fetcher)
    assert res["status"] == "ok"
    assert res["options"][0]["currency"] == "EUR"  # echoed canonical, matching the prices


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
    assert top["total"] == top["priced_total"]     # equal when complete
    # options are price-ranked
    totals = [o["total"] for o in res["options"]]
    assert totals == sorted(totals)
    # fully-priced searches carry no hints; provenance names the injected source
    assert res["hints"] == {}
    assert res["sources"] == ["mock"]


def test_sources_lists_composite_children():
    res = search_trip(CANONICAL, CompositeFetcher([MockFetcher(), NoneFetcher()]))
    assert res["sources"] == ["mock", "none"]


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
        assert opt["total"] is None                    # an unpriced leg -> no trip total
        assert opt["priced_total"] == round(sum(pl["price"] for pl in opt["legs"]), 2)
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
    assert res["hints"] == {}                      # per-date sources see nothing off-window


def test_hints_surface_near_window_fares_for_missing_legs_only():
    # leg1 (AAA->BBB) window Sep 10-16: priced in-window, plus off-window extras that must
    # NOT surface (the leg isn't missing). leg2 (BBB->AAA) window Sep 20-28: the calendar
    # only has dates outside it - 5 before, 2 after - so leg2 goes unpriced and its hints
    # must keep the nearest 3 per side, date-ascending. quote() raising doubles as proof
    # that the empty in-window calendar was authoritative (no per-date re-probe).
    q = {"origins": ["AAA"], "stops": [["BBB"], ["AAA"]], "earliest": "2026-09-10",
         "latest": "2026-09-16", "stays": [[10, 12]]}
    fetcher = CalendarOnlyFetcher({
        ("AAA", "BBB"): {date(2026, 9, 2): 400.0, date(2026, 9, 12): 500.0,
                         date(2026, 9, 20): 450.0},
        ("BBB", "AAA"): {date(2026, 9, d): 300.0 + d for d in (14, 15, 16, 17, 18, 29, 30)},
    })
    res = search_trip(q, fetcher)
    assert res["status"] == "partial" and res["missing_legs"] == ["leg2"]

    opt = res["options"][0]
    assert opt["total"] is None and opt["priced_total"] == 500.0
    assert opt["legs"][0]["fetched_at"] == "2026-07-01"

    assert set(res["hints"]) == {"leg2"}           # covered legs never get hints
    hints = res["hints"]["leg2"]
    assert [h["date"] for h in hints] == ["2026-09-16", "2026-09-17", "2026-09-18",
                                          "2026-09-29", "2026-09-30"]
    h = hints[0]
    assert h["from"] == "BBB" and h["to"] == "AAA" and h["price"] == 316.0
    assert h["source"] == "calonly" and h["bookable"] is False
    assert h["fetched_at"] == "2026-07-01"


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
    assert q.fetched_at and "T" in q.fetched_at    # no search_date in link -> fetch stamp
    assert f.parse_offer({"airline": "IB"}) is None            # no price -> no quote


def test_parse_offer_travelpayouts_freshness_from_link():
    # v3 offers expose no freshness field, but the link embeds the Aviasales observation
    # date as search_date=DDMMYYYY - the honest "how stale is this cached fare" signal.
    f = TravelpayoutsFetcher("tok")
    q = f.parse_offer({"price": 500,
                       "link": "/search/MVD0809MAD1?t=abc&search_date=27062026&x=1"})
    assert q.fetched_at == "2026-06-27"


def test_parse_offer_serpapi():
    f = SerpApiFetcher("key")
    q = f.parse_offer({"price": 780, "booking_token": "xyz",
                       "flights": [{"airline": "Iberia", "flight_number": "IB 6842"}]})
    assert q.price == 780.0 and q.source == "serpapi" and q.bookable is True
    assert q.airline == "Iberia" and q.flight_number == "IB 6842"
    assert q.link is None                                       # booking_token != URL (deferred)
    assert q.fetched_at and "T" in q.fetched_at    # live fare -> stamped at fetch time


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} passed")
