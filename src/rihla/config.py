# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leandro Garcia
"""
config.py - environment-driven fetcher selection, print-free.

The selection logic that used to live in `cli.choose_fetcher()`, returning
(fetcher, notes) instead of printing: the CLI prints the notes to stdout; the MCP
server routes them to stderr, because over stdio stdout is the JSON-RPC stream and
any stray print corrupts it (see docs/mcp-readiness.md).
"""
from __future__ import annotations

import os
from typing import Optional

from rihla.fetchers import (
    CalendarCacheFetcher,
    CompositeFetcher,
    MockFetcher,
    PriceFetcher,
    SerpApiFetcher,
    TravelpayoutsFetcher,
)

_DEFAULT_CALENDAR_TTL = 3600.0


def _calendar_ttl(e: dict) -> float:
    """RIHLA_CALENDAR_TTL seconds; 0 (or negative) disables the calendar cache."""
    raw = str(e.get("RIHLA_CALENDAR_TTL", "")).strip()
    if not raw:
        return _DEFAULT_CALENDAR_TTL
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_CALENDAR_TTL


def build_fetcher(env: Optional[dict] = None,
                  currency: str = "USD") -> tuple[PriceFetcher, list[str]]:
    """Build the data source from RIHLA_PROFILE + whatever keys are present.

    local  (default): every source whose key is set, incl. SerpApi BYOK.
    hosted          : redistribution-licensed sources only (SerpApi disabled).
    mock            : force the offline MockFetcher.

    `currency` is threaded into every priced source (each normalizes to its own wire
    format), so a fetcher instance serves exactly one currency - callers wanting more
    build one per currency (which also keeps each calendar cache single-currency).

    Returns (fetcher, notes) - notes are the human-readable profile/source banners,
    left to the caller to render (CLI: stdout; MCP server: stderr).
    """
    e: dict = os.environ if env is None else env       # injectable for tests
    currency = str(currency).strip().upper() or "USD"
    notes: list[str] = []
    profile = e.get("RIHLA_PROFILE", "local").strip().lower()
    if profile == "mock":
        notes.append("(RIHLA_PROFILE=mock - offline MockFetcher)")
        return MockFetcher(), notes

    fetchers: list[PriceFetcher] = []
    if e.get("TRAVELPAYOUTS_TOKEN"):
        tp: PriceFetcher = TravelpayoutsFetcher(e["TRAVELPAYOUTS_TOKEN"], currency=currency)
        ttl = _calendar_ttl(e)
        if ttl > 0:                # wrap ONLY calendar-capable sources (see fetchers/cache.py)
            tp = CalendarCacheFetcher(tp, ttl_seconds=ttl)
            notes.append(f"(calendar cache: ttl={ttl:g}s; RIHLA_CALENDAR_TTL=0 disables)")
        fetchers.append(tp)
    if e.get("SERPAPI_KEY"):
        if profile == "hosted":
            notes.append("(profile=hosted - SerpApi disabled: licensed sources only)")
        else:
            fetchers.append(SerpApiFetcher(e["SERPAPI_KEY"], currency=currency))

    if not fetchers:
        notes.append("(no data-source keys set - offline MockFetcher)")
        return MockFetcher(), notes
    notes.append(f"(profile={profile} | sources: {', '.join(f.name for f in fetchers)} "
                 f"| currency: {currency})")
    return (CompositeFetcher(fetchers) if len(fetchers) > 1 else fetchers[0]), notes
