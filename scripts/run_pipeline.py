"""Refresh every source and rebuild the site data. Run on a schedule by .github/workflows/update.yml.

A failed step is reported and skipped; the previous data for that source is kept.
Usage: python scripts/run_pipeline.py [--force-zillow]
Env: CL_DETAIL_LIMIT caps new Craigslist detail pages fetched per run (default 300, ~1 per second).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
ZILLOW_EVERY_DAYS = 3  # a full Zillow pull costs ~$0.70 on Apify
FACEBOOK_WINDOW = "8 hours"  # the schedule runs every 6 hours; the overlap catches late posts
PLACES_EVERY_DAYS = 7
CL_SEARCH, CL_DETAILS = "data/raw/craigslist_search", "data/raw/craigslist_details"


def run(name, *args):
    print(f"\n== {name}", flush=True)
    ok = subprocess.run([PY, *args], cwd=ROOT).returncode == 0
    if not ok:
        print(f"!! {name} failed; keeping previous data", flush=True)
    return ok


def main():
    failed = []
    if not (run("Craigslist search", "-I", "scripts/craigslist/fetch_search.py", CL_SEARCH)
            and run("Craigslist details", "-I", "scripts/craigslist/fetch_details.py", CL_SEARCH, CL_DETAILS,
                   os.environ.get("CL_DETAIL_LIMIT") or "300")
            and run("Craigslist normalize", "-I", "scripts/craigslist/normalize.py", CL_SEARCH, CL_DETAILS,
                    "data/raw/craigslist.json", "data/listings/craigslist.json")):
        failed.append("craigslist")

    window = FACEBOOK_WINDOW if (ROOT / "data/raw/facebook.json").exists() else "30 days"
    if not (run("Facebook pull", "scripts/fetch_facebook.py", window)
            and run("Facebook sort", "scripts/parse_facebook.py")):
        failed.append("facebook")

    stamp = ROOT / "data/work/zillow_pulled_at"
    due = "--force-zillow" in sys.argv or not stamp.exists() or time.time() - float(stamp.read_text()) > ZILLOW_EVERY_DAYS * 86400
    if due:
        if run("Zillow pull", "scripts/fetch_zillow.py", "2000"):
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(str(time.time()))
        else:
            failed.append("zillow")
    # Detail pages (features, floor plans) only for listings not fetched before, so usually free.
    if not run("Zillow details", "scripts/fetch_zillow_details.py"):
        failed.append("zillow details")
    if not run("Zillow normalize", "scripts/normalize_zillow.py"):
        failed.append("zillow")

    # Shops, restaurants, groceries, parks and transit for walkability; they change slowly.
    places = ROOT / "data/raw/places.json"
    if not places.exists() or time.time() - places.stat().st_mtime > PLACES_EVERY_DAYS * 86400:
        if not run("Places (OpenStreetMap)", "scripts/fetch_places.py"):
            failed.append("places")

    if not run("Who posted (Craigslist/Facebook)", "scripts/classify_lister.py"):
        failed.append("lister classification")

    if not run("Merge", "scripts/merge_listings.py"):
        sys.exit(1)
    print("\nFailed sources:", ", ".join(failed) if failed else "none")


if __name__ == "__main__":
    main()
