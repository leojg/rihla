"""
Tests for the place-resolution seam (resolve.py): exact-code matching over the fuzzy
autocomplete response (the linchpin), both response shapes (airport vs city), and the
resolve_places grouping/unresolved contract - all pure, on JSON captured live 2026-07-01.
Runnable via pytest OR standalone: `python tests/test_resolve.py`.
"""
from rihla.resolve import ResolvedAirport, parse_places, resolve_places

# Captured from autocomplete.travelpayouts.com/places2 (2026-07-01), trimmed to the
# fields resolve.py touches (+ type/weight to keep the shape realistic).
EZE_RESPONSE = [
    {"type": "airport", "code": "EZE", "name": "Ministro Pistarini Airport",
     "city_name": "Buenos Aires", "country_name": "Argentina", "country_code": "AR",
     "coordinates": {"lon": -58.539833, "lat": -34.81273}, "weight": 2228},
]
# term=montevideo -> the Uruguayan capital (MVD) AND Montevideo, Minnesota (MVE).
MONTEVIDEO_RESPONSE = [
    {"type": "city", "code": "MVD", "name": "Montevideo",
     "country_name": "Uruguay", "country_code": "UY",
     "coordinates": {"lon": -56.1819444, "lat": -34.8836111},
     "main_airport_name": "Carrasco International Airport", "weight": 537},
    {"type": "city", "code": "MVE", "name": "Montevideo",
     "country_name": "United States", "country_code": "US",
     "coordinates": {"lon": -95.71667, "lat": 44.95},
     "main_airport_name": "Montevideo-Chippewa", "weight": 1},
]
# term=ZZZZ -> the endpoint fuzzily "finds" SZB. Non-empty proves nothing.
ZZZZ_RESPONSE = [
    {"type": "airport", "code": "SZB", "name": "Sultan Abdul Aziz Shah Airport",
     "city_name": "Kuala Lumpur", "country_name": "Malaysia", "country_code": "MY",
     "coordinates": {"lon": 101.558075, "lat": 3.130644}, "weight": 128},
]


def test_parse_places_airport_shape():
    r = parse_places("EZE", EZE_RESPONSE)
    assert r == ResolvedAirport("EZE", "airport", "Ministro Pistarini Airport",
                                "Buenos Aires", "Argentina", "AR", -34.81273, -58.539833)


def test_parse_places_city_shape_and_exact_code_disambiguation():
    # exact-code match must pick MVD (Uruguay), never the fuzzy sibling MVE (US);
    # city entries have no city_name -> the city is `name` itself.
    r = parse_places("MVD", MONTEVIDEO_RESPONSE)
    assert r is not None and r.code == "MVD" and r.country_code == "UY"
    assert r.kind == "city" and r.city == "Montevideo"
    assert parse_places("mvd", MONTEVIDEO_RESPONSE) == r      # case-insensitive


def test_parse_places_rejects_fuzzy_garbage():
    # the linchpin: ZZZZ gets a non-empty (SZB) response, but no exact match -> None.
    assert parse_places("ZZZZ", ZZZZ_RESPONSE) is None


def test_parse_places_empty_and_failed_responses():
    assert parse_places("MVD", []) is None
    assert parse_places("MVD", None) is None                  # get_json network failure


def _fake_validator(code):
    known = {
        "MVD": ResolvedAirport("MVD", "city", "Montevideo", "Montevideo",
                               "Uruguay", "UY", -34.88, -56.18),
        "EZE": ResolvedAirport("EZE", "airport", "Ministro Pistarini Airport",
                               "Buenos Aires", "Argentina", "AR", -34.81, -58.54),
    }
    return known.get(str(code).strip().upper())


def test_resolve_places_groups_and_collects_unresolved():
    out = resolve_places(
        [{"role": "origin", "query": "montevideo",
          "primary": ["MVD"], "nearby": ["EZE", "XXQ"]},
         {"role": "stop 1", "query": "europe", "primary": ["MONTEVIDEO"]}],
        validator=_fake_validator,
    )
    origin, stop = out["places"]
    assert [a["code"] for a in origin["primary"]] == ["MVD"]
    assert [a["code"] for a in origin["nearby"]] == ["EZE"]
    assert origin["nearby"][0]["city"] == "Buenos Aires"      # enrichment survives
    assert origin["unresolved"] == ["XXQ"]
    assert stop["primary"] == [] and stop["nearby"] == []
    assert stop["unresolved"] == ["MONTEVIDEO"]               # slipped city name, loud
    assert out["unresolved"] == ["XXQ", "MONTEVIDEO"]
    assert "confirm" in out["note"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} passed")
