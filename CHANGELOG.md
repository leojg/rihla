# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-03

First public release.

### Added
- Multi-leg, multi-airport flight-search engine: airport-set substitution per leg,
  flexible date windows, stay-duration constraints linking legs, and a pure local
  optimizer that enumerates combinations over a once-fetched price grid.
- Data sources behind a one-method `PriceFetcher` protocol: Travelpayouts (primary;
  cached, indicative, calendar-first fetching) and SerpApi / Google Flights (BYO-key
  fill for routes Travelpayouts misses), merged cheapest-bookable-over-cached; plus a
  deterministic offline `MockFetcher`.
- `rihla` CLI: run a query from a JSON file, build one interactively (`-i`), show
  booking links (`--links`), select sources with `RIHLA_PROFILE` (local/hosted/mock).
- MCP server (`rihla-mcp`, stdio): `resolve_airports` (quota-free validation and
  enrichment of proposed IATA codes) and `search_trip` (the priced search), with the
  resolve → confirm → search etiquette encoded in the tool descriptions.
- Result transparency: `ok` / `partial` / `no_coverage` / `constraints_unsatisfiable`
  statuses, bookable-vs-cached tags with per-leg observation dates, and nearest
  out-of-window fare hints for unpriced legs.

[0.1.0]: https://github.com/leojg/rihla/releases/tag/v0.1.0
