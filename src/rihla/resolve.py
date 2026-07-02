"""
resolve.py - free-text place -> validated airport codes: the resolution seam.

"LLM proposes, API validates" (ADR-0004): the MCP client agent parses the traveler's
words and proposes IATA codes - including nearby alternatives it already knows (e.g.
Buenos Aires EZE/AEP for Montevideo) - and this module validates each code against the
Travelpayouts autocomplete API and enriches it (name / city / country / coordinates).
No bundled airport dataset, no server-side LLM.

This is a second, quota-free network boundary next to `fetchers.build_grid` (the priced,
quota-limited one). It follows the fetchers' recipe: a thin network mapper
(`validate_code`) over a pure, fixture-testable parser (`parse_places`).

CAUTION: the autocomplete endpoint is fuzzy, not a validator - `term=ZZZZ` happily
returns SZB. Validation is therefore "some returned element's `code` equals the proposed
code", never "did it return anything".
"""
from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass
from typing import Optional

from rihla.fetchers._http import get_json

AUTOCOMPLETE_URL = "https://autocomplete.travelpayouts.com/places2"


@dataclass(frozen=True)
class ResolvedAirport:
    """One validated place: an IATA code enriched with what autocomplete knows about it."""
    code: str
    kind: str                   # "airport" | "city" (a city code like MVD is metro-level)
    name: str
    city: str
    country: str
    country_code: str
    lat: Optional[float]
    lon: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def parse_places(code: str, raw) -> Optional[ResolvedAirport]:
    """Pick the element of an autocomplete response whose code matches exactly - PURE.

    `raw` is the endpoint's top-level array (or None on network failure). Returns None
    unless some element's `code` equals `code` case-insensitively: the endpoint is
    fuzzy, so a non-empty response proves nothing about the proposed code.
    """
    code = str(code).strip().upper()
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict) or str(item.get("code") or "").upper() != code:
            continue
        coords = item.get("coordinates") or {}
        return ResolvedAirport(
            code=code,
            kind=item.get("type") or "",
            name=item.get("name") or "",
            # airports carry the city in `city_name`; city entries ARE the city (`name`)
            city=item.get("city_name") or item.get("name") or "",
            country=item.get("country_name") or "",
            country_code=item.get("country_code") or "",
            lat=coords.get("lat"),
            lon=coords.get("lon"),
        )
    return None


def validate_code(code: str, timeout: int = 10) -> Optional[ResolvedAirport]:
    """Validate one proposed IATA code against autocomplete - NETWORK, token-free.

    The URL is built by hand: the endpoint expects literal repeated `types[]=` params,
    which urlencode's bracket escaping does not reliably reproduce.
    """
    term = urllib.parse.quote(str(code).strip())
    url = f"{AUTOCOMPLETE_URL}?term={term}&locale=en&types[]=city&types[]=airport"
    # get_json is annotated -> Optional[dict] but passes this endpoint's array through.
    return parse_places(code, get_json(url, timeout=timeout))


def resolve_places(places: list, validator=validate_code) -> dict:
    """Validate a batch of proposed places - the orchestrator the MCP resolve tool wraps.

    Each input item: {"role": ..., "query": <traveler's words>, "primary": [codes],
    "nearby": [codes]}. The output mirrors the items with every code replaced by its
    enriched dict, plus the codes autocomplete could not confirm (per item and collected
    top-level in `unresolved` - the visible fallback for a slipped city name).
    """
    out: list[dict] = []
    unresolved_all: list[str] = []
    for item in places:
        resolved: dict = {"role": item.get("role", ""), "query": item.get("query", "")}
        unresolved: list[str] = []
        for group in ("primary", "nearby"):
            enriched = []
            for code in item.get(group) or []:
                r = validator(code)
                if r is None:
                    unresolved.append(str(code).strip().upper())
                else:
                    enriched.append(r.to_dict())
            resolved[group] = enriched
        resolved["unresolved"] = unresolved
        unresolved_all += unresolved
        out.append(resolved)
    return {
        "places": out,
        "unresolved": unresolved_all,
        "note": "Present these airports (including nearby alternatives) to the traveler "
                "and get explicit confirmation before calling search_trip.",
    }
