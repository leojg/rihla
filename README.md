# Rihla

> **Rihla** (رحلة), *"the journey."* Named for Ibn Battuta's 14th-century travelogue —
> the record of history's farthest-traveling explorer, who left Tangier for Mecca and
> kept going for 29 years and 75,000 miles.

Flexible multi-leg, multi-airport flight search that finds the cheapest route across an
**entire itinerary** — available as a CLI and as an MCP server for AI agents.

Consumer flight sites price one leg at a time. Rihla treats the whole trip as a single
optimization problem:

> *"Leave Montevideo — or Buenos Aires, it's a ferry ride away — around September 15
> for Europe. Stay 20–30 days, then Japan for 15, then home. What's the cheapest
> combination?"*

That query has three legs, flexible airports on both ends of each, a flexible departure
window, and stay-duration constraints linking the legs. Rihla prices each leg's
date×airport grid once, then finds the cheapest valid combinations in pure local
compute — so even a 3–4 leg flexible query costs only a handful of API calls.

```
1. 1,297 USD   (44 days door-to-door)
     MVD -> AMS  2026-09-08  $    383  [mock, cached]  AA AA127
     FRA -> NRT  2026-10-07  $    481  [mock, cached]  KL KL411
     HND -> EZE  2026-10-22  $    433  [mock, cached]  AZ AZ933

2. 1,308 USD   (44 days door-to-door)
     MVD -> AMS  2026-09-14  $    446  [mock, cached]  AA AA127
     ...
```

Note the airport substitution at work: it enters Europe through Amsterdam, leaves from
Frankfurt, and flies home into Buenos Aires — each leg independently picks the cheapest
airport pair from its sets.

## Quick start

Requires Python ≥ 3.10.

```bash
pip install rihla            # CLI
pip install "rihla[mcp]"     # CLI + MCP server
```

Runs offline out of the box (no keys needed — a deterministic mock data source):

```bash
RIHLA_PROFILE=mock rihla                # the canonical demo trip above
rihla examples/queries/canonical.json   # same trip, from a query file
rihla -i                                # build a query interactively
```

For live prices, copy `.env.example` to `.env` and add at least a
[Travelpayouts](https://www.travelpayouts.com) token (free). See
[Data sources](#data-sources--profiles).

## Writing a query

A query is a small JSON file: your origin airports, the ordered stops, a departure
window for the first leg, and how long to stay at each stop. Downstream date windows
are derived — you never hand-compute "if I leave Sep 15 and stay 20–30 days, when do I
fly to Tokyo?"

```json
{
  "origins": ["MVD", "EZE", "AEP"],
  "stops": ["EUROPE", ["NRT", "HND"], "MVD_AREA"],
  "earliest": "2026-09-08",
  "latest": "2026-09-22",
  "stays": [[20, 30], [15, 15]],
  "date_step": 3,
  "top": 5
}
```

- **`origins`** — IATA codes tried as one origin set; the cheapest wins per date.
- **`stops`** — each stop is a region name or a list of IATA codes. Built-in regions:
  `EUROPE` (MAD, BCN, LIS, CDG, FCO, AMS, FRA), `TOKYO` (NRT, HND), `MVD_AREA`
  (MVD, EZE, AEP). Make the last stop your origin set to fly home.
- **`earliest` / `latest`** — the departure window for the *first* leg only.
- **`stays`** — `[min, max]` nights at each intermediate stop
  (`len(stays) == len(stops) - 1`).
- **`date_step`** — sample every N days across date windows (coarser = fewer API calls).
- **`top`** — how many ranked combinations to return.
- **`currency`** — optional ISO 4217 code (default `USD`).

`rihla -i` walks you through these questions and prints the resulting JSON to save for
reuse. Add `--links` to any run to show booking URLs.

## Reading results

Rihla is honest about data quality rather than pretending everything is bookable:

- Each flight is tagged with its source, and `cached` when the price is **indicative**
  (Travelpayouts data is aggregated search history, not a live fare) versus a real,
  bookable fare (SerpApi / Google Flights).
- If some legs can't be priced (thin routes are real — cached sources have gaps), you
  get a **partial** result over the legs that were found, never a silently wrong total.
- For unpriced legs, Rihla shows the nearest cached fares *outside* your departure
  window — a hint to shift or widen dates.

Ranking is price-only in v0.1. Open-jaw within a region is allowed by default (enter
Europe at one city, leave from another); the cost of repositioning inside the region is
not modeled.

## Data sources & profiles

| Source | Role | Cost | Notes |
|---|---|---|---|
| **Travelpayouts / Aviasales** | Primary | Free | Cached, redistribution-licensed. A month of prices per call, so the call budget stays tiny. Prices indicative; coverage follows route popularity. |
| **SerpApi** (Google Flights) | Fill | 250 free searches/mo (BYO key) | Real bookable fares; fills routes Travelpayouts misses. Only spent on uncovered routes. |
| **Mock** | Offline | — | Deterministic fake prices for development and demos. |

Configure via `.env` (see `.env.example`) or environment variables:
`TRAVELPAYOUTS_TOKEN`, `SERPAPI_KEY`, and `RIHLA_PROFILE`:

- `local` (default) — every source whose key is set, including SerpApi.
- `hosted` — redistribution-licensed sources only (SerpApi disabled: it scrapes Google,
  so **do not serve it from a public hosted instance**).
- `mock` — force the offline fetcher, no network.

With no keys set, Rihla falls back to the mock source and says so.

## MCP server

Rihla ships an MCP server (stdio) so agents like Claude can run trip searches:

```bash
pip install "rihla[mcp]"
claude mcp add rihla -- rihla-mcp        # Claude Code
```

or in any MCP client config:

```json
{
  "mcpServers": {
    "rihla": {
      "command": "rihla-mcp",
      "env": {
        "TRAVELPAYOUTS_TOKEN": "your-token",
        "SERPAPI_KEY": "your-key"
      }
    }
  }
}
```

(The server also loads a `.env` from its working directory, so `env` is optional if you
run it from a checkout.)

It exposes two read-only tools with an enforced etiquette:

1. **`resolve_airports`** — the agent proposes IATA codes for the traveler's named
   places; Rihla validates and enriches them (nearby alternatives included). Cheap and
   quota-free.
2. **`search_trip`** — the priced, quota-limited search. Tool descriptions instruct the
   agent to get the traveler's explicit confirmation of the airports *before* spending
   quota here.

mcp-name: io.github.leojg/rihla

## How it works

Leg prices are independent — the MVD→Europe fare doesn't depend on the Tokyo dates. So
Rihla fetches each leg's date×airport grid **once**, then enumerates valid date
combinations (respecting the stay constraints) entirely in memory. The combinatorial
explosion lives in local compute, not in API calls.

```
core.py            data model + the pure optimizer (no I/O)
fetchers/          PriceFetcher protocol: Mock / Travelpayouts / SerpApi + merge
places.py          airport sets / regions
api.py             search_trip: serializable query in, result dict out
cli.py             thin CLI over search_trip
mcp_server.py      thin MCP wrapper over the same seam
```

Adding a data source (Duffel, Kiwi, …) is one more class implementing a one-method
protocol: `quote(origin, dest, day) -> Quote`.

**Scope (v0.1):** flight search only — no lodging, no booking or payments, single adult,
one cabin. Search returns booking links, never handles the transaction.

## Development

```bash
git clone https://github.com/leojg/rihla && cd rihla
pip install -e ".[dev,mcp]"
pytest              # offline, no keys needed
ruff check .
```

## License

Licensed under the Apache License 2.0 — see [LICENSE](LICENSE).
