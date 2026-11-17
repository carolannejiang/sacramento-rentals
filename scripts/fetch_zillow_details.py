"""Fetch Zillow detail pages (features, amenities, floor plans) for listings not fetched yet.

Results are cached in data/raw/zillow_details.json, keyed by listing URL, so each listing is
only paid for once (~$0.003 each on Apify).
Usage: python3 scripts/fetch_zillow_details.py [max_new]
"""
import json
import sys

from apify import ROOT, run_actor

CACHE = ROOT / "data/raw/zillow_details.json"


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    raw = ROOT / "data/raw/zillow.json"
    if not raw.exists():
        print("No Zillow search results yet; nothing to fetch")
        return
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    urls = [x["propertyUrl"] for x in json.loads(raw.read_text()) if x.get("listingStatus") == "forRent"]
    todo = [u for u in dict.fromkeys(urls) if u not in cache][:limit]
    print(f"{len(todo)} Zillow listings need details ({len(cache)} cached)")
    if not todo:
        return
    items = run_actor("maxcopell~zillow-detail-scraper", {
        "startUrls": [{"url": u} for u in todo],
        "propertyStatus": "FOR_RENT",
    })
    for it in items:
        url = it.get("addressOrUrlFromInput") or it.get("propertyUrl")
        if url:
            cache[url] = it
    CACHE.write_text(json.dumps(cache))
    print(f"Saved details for {len(items)} listings")


if __name__ == "__main__":
    main()
