"""Pull rentals for the Zillow searches in sources/zillow_searches.json via Apify.

Usage: python3 scripts/fetch_zillow.py [max_results_per_search]
Writes data/raw/zillow.json.
"""
import json
import sys

from apify import ROOT, run_actor, save


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    searches = json.loads((ROOT / "sources/zillow_searches.json").read_text())
    items = run_actor("maxcopell~zillow-scraper", {
        "searchUrls": [{"url": s["url"]} for s in searches],
        "extractionMethod": "PAGINATION_WITH_ZOOM_IN",
        "resultsLimit": limit,
    })
    save(items, "zillow.json")


if __name__ == "__main__":
    main()
