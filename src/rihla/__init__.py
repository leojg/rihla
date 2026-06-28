"""
Rihla - flexible multi-leg, multi-airport flight search.

Finds the cheapest valid combination of flights across an entire multi-stop
itinerary, with flexible date windows, airport-set substitution, and stay-duration
constraints between legs.

Layout:
  core        - data model + the pure optimizer (no I/O, no rihla deps)
  fetchers/   - the price-fetch layer (PriceFetcher protocol, Mock + Amadeus, build_grid)
  places      - predefined airport sets / regions + the canonical example trip
  cli         - run a query from the command line
"""
from rihla.core import (
    Bundle,
    Gap,
    Leg,
    Place,
    PricedLeg,
    Trip,
    linear_trip,
    optimize,
)
from rihla.fetchers import AmadeusFetcher, MockFetcher, PriceFetcher, build_grid, fetch_leg

__version__ = "0.1.0"

__all__ = [
    "Place", "Leg", "Gap", "PricedLeg", "Trip", "Bundle", "linear_trip", "optimize",
    "PriceFetcher", "build_grid", "fetch_leg", "MockFetcher", "AmadeusFetcher",
    "__version__",
]
