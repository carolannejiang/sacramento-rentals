# Sacramento Rentals

Personal apartment-hunt aggregator. Pulls whole-unit rentals from Craigslist, Zillow, Redfin and
Sacramento Facebook housing groups into one filterable page with a map. A GitHub Actions
workflow refreshes it every 6 hours and publishes `site/` to GitHub Pages and Vercel
(https://sacramento-rentals.vercel.app).

## Pipeline (`scripts/run_pipeline.py`)

| Source | How | Cadence |
|---|---|---|
| Craigslist | Search API split into price bands + detail pages (`scripts/craigslist/`) | every run |
| Facebook groups (`sources/facebook_groups.json`) | Apify `apify/facebook-groups-scraper`, then Claude sorts posts (`parse_facebook.py`) | every run, last 8 hours |
| Zillow (`sources/zillow_searches.json`) | Apify `maxcopell/zillow-scraper`; features from `maxcopell/zillow-detail-scraper` for new listings only | every 3 days |
| Redfin (all Sacramento city rentals) | Redfin's search API + amenities/floor plans for new listings (`fetch_redfin.py`); its Zillow-fed copies fold into Zillow | every run |

Walkability comes from OpenStreetMap shops, restaurants, groceries, parks and transit
(`fetch_places.py`, weekly; scored in `walkability.py`). Median household income and the share
of adults with a bachelor's degree come from the census tract each address is in (Census
Reporter, `fetch_census.py`, monthly); the median asking price per sqft of homes for sale comes
from the ZIP code (Realtor.com research data, `fetch_asking_prices.py`, weekly); rent per sqft is
compared with current listings within half a mile (`area_stats.py`).

Listings with no usable address (mostly Facebook) get an approximate area instead: Claude names
the places a post mentions — cross streets, a street, a nearby school or complex, a neighborhood,
a ZIP (`place_hints.py`) — and the first one OpenStreetMap can find is outlined on the map
(`approx_area.py`).

`merge_listings.py` drops shared rooms and rented posts, collapses cross-posts, and writes
`site/listings.json` (poster names removed).

Working data lives in the Actions cache; `seed/` (from `scripts/make_seed.py`) is the starting
point when the cache is empty.

## Secrets

- `APIFY_TOKEN`
- `ANTHROPIC_API_KEY`
- `VERCEL_TOKEN` (optional; the Vercel step is skipped without it). Repo variables
  `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` point at the Vercel project.

## Run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/run_pipeline.py
python3 -m http.server -d site 8765
```
