"""
fetchers/_http.py - shared HTTP transport for the network-touching fetchers.

The `urllib` request + timeout + "any failure means no data" boilerplate, in one place,
so each provider stays a thin response-mapper (implement `PriceFetcher`, map the raw
response to a `Quote` via a pure `parse_offer` - the add-a-provider recipe in ADR-0001).
Stdlib only (zero install).
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional


def get_json(url: str, timeout: int, ua: str = "rihla/0.1") -> Optional[dict]:
    """GET `url` and parse JSON, or None on any failure (network, HTTP, decode)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:                       # noqa: BLE001 - treat any failure as "no data"
        return None
