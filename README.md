# Sacramento Rentals

Personal apartment-hunt aggregator. Pulls whole-unit rentals from Craigslist, Zillow and
Sacramento Facebook housing groups into one filterable page with a map. A GitHub Actions
workflow refreshes it every 6 hours and publishes `site/` to GitHub Pages.

## Pipeline (`scripts/run_pipeline.py`)

| Source | How | Cadence |
|---|---|---|
| Craigslist | Search API split into price bands + detail pages (`scripts/craigslist/`) | every run |
| Facebook groups (`sources/facebook_groups.json`) | Apify `apify/facebook-groups-scraper`, then Claude sorts posts (`parse_facebook.py`) | every run, last 8 hours |
| Zillow (`sources/zillow_searches.json`) | Apify `maxcopell/zillow-scraper` | every 3 days |

`merge_listings.py` drops shared rooms and rented posts, collapses cross-posts, and writes
`site/listings.json` (poster names removed).

Working data lives in the Actions cache; `seed/` (from `scripts/make_seed.py`) is the starting
point when the cache is empty.

## Secrets

- `APIFY_TOKEN`
- `ANTHROPIC_API_KEY`

## Run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/run_pipeline.py
python3 -m http.server -d site 8765
```
