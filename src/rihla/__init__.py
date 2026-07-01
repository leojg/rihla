"""
Rihla - flexible multi-leg, multi-airport flight search.

Finds the cheapest valid combination of flights across an entire multi-stop
itinerary, with flexible date windows, airport-set substitution, and stay-duration
constraints between legs.

Layout:
  core        - data model + the pure optimizer (no I/O, no rihla deps)
  fetchers/   - the price-fetch layer (PriceFetcher, Mock/Travelpayouts/SerpApi, merge, build_grid)
  places      - predefined airport sets / regions + the canonical example trip
  api         - search_trip: serializable Query in, result dict out (the CLI/MCP seam)
  cli         - run a query from the command line
"""
from rihla.api import Query, search_trip
from rihla.core import (
    Bundle,
    Gap,
    Leg,
    Place,
    PricedLeg,
    Quote,
    Trip,
    linear_trip,
    optimize,
    optimize_partial,
)
from rihla.fetchers import (
    CompositeFetcher,
    MockFetcher,
    PriceFetcher,
    SerpApiFetcher,
    TravelpayoutsFetcher,
    build_grid,
    fetch_leg,
    merge_quotes,
)

__version__ = "0.1.0"

__all__ = [
    "Place", "Leg", "Gap", "Quote", "PricedLeg", "Trip", "Bundle", "linear_trip",
    "optimize", "optimize_partial",
    "Query", "search_trip",
    "PriceFetcher", "build_grid", "fetch_leg", "merge_quotes", "CompositeFetcher",
    "MockFetcher", "TravelpayoutsFetcher", "SerpApiFetcher", "__version__",
]
