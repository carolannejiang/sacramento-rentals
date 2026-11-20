"""Pull Sacramento rentals from Redfin's own search API (the data behind
https://www.redfin.com/city/16409/CA/Sacramento/rentals), plus amenities and floor plans
for up to N rentals not fetched before (polite: ~1 request/sec).

Redfin mixes in Zillow's feed; those copies are folded into the Zillow listing by merge_listings.py.
Usage: python3 -I fetch_redfin.py [N]
Writes data/raw/redfin.json and data/raw/redfin_details/<rentalId>.json.
"""
import json, os, subprocess, sys, time

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
API = "https://www.redfin.com/stingray/api/v1"
SEARCH = (API + "/search/rentals?al=1&isRentals=true&region_id=16409&region_type=6&status=9"
          "&uipt=1,2,3,4&use_max_home_count=true&v=8&num_homes=350")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DETAILS = os.path.join(ROOT, "data/raw/redfin_details")


def get(url):
    r = subprocess.run(["curl", "-s", "-A", UA, "-w", "\n%{http_code}", url], capture_output=True, text=True)
    body, _, status = r.stdout.rpartition("\n")
    return status, body


def search(extra=""):
    homes, page = [], 1
    while True:
        status, body = get(f"{SEARCH}&page_number={page}&start={(page - 1) * 350}{extra}")
        if status != "200":
            sys.exit(f"search page {page} returned {status}")
        d = json.loads(body)
        homes += d["homes"]
        # Pages sometimes come back a few short of 350 mid-search, so only an empty page ends it.
        if not d["homes"] or len(homes) >= d["numMatchedHomes"]:
            return list({h["homeData"]["propertyId"]: h for h in homes}.values())
        page += 1
        time.sleep(1.2)


n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
homes = search()
# Redfin's "dogs allowed" filter is the only dog-specific pet data it has.
dogs = {h["homeData"]["propertyId"] for h in search("&dogs_allowed=true")}
for h in homes:
    h["dogsAllowed"] = h["homeData"]["propertyId"] in dogs
out = os.path.join(ROOT, "data/raw/redfin.json")
os.makedirs(DETAILS, exist_ok=True)
json.dump(homes, open(out, "w"), indent=1, ensure_ascii=False)
print(f"Saved {len(homes)} rentals ({len(dogs)} allow dogs)")

def details(rid):
    """{"amenities": ..., "floorPlans": ...}, or None if Redfin is blocking us."""
    out = {}
    for part in ("amenities", "floorPlans"):
        status, body = get(f"{API}/rentals/{rid}/{part}")
        time.sleep(0.6)
        if status in ("403", "429"):
            return None
        try:
            out[part] = json.loads(body) if status == "200" else None
        except ValueError:  # a challenge page instead of JSON
            return None
    return out


# The search results are already saved, so a block here only delays amenities to a later run.
fetched = 0
for h in homes:
    rid = h["rentalExtension"]["rentalId"]
    path = os.path.join(DETAILS, f"{rid}.json")
    if fetched >= n:
        break
    if os.path.exists(path):
        continue
    detail = details(rid)
    if detail is None:
        print(f"blocked after {fetched} detail fetches; the rest wait for the next run")
        break
    json.dump(detail, open(path, "w"), ensure_ascii=False)
    fetched += 1
print("fetched details for", fetched)
