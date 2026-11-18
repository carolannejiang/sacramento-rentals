"""Pull shops, restaurants, groceries, parks and transit stops around Sacramento from
OpenStreetMap (Overpass API, free) into data/raw/places.json as [lat, lon, kind] rows.

Kinds: food (restaurants, cafes, bars), shop, grocery, park, transit.
Usage: python3 scripts/fetch_places.py
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BBOX = "38.38,-121.60,38.76,-121.10"  # south, west, north, east: covers the listings
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = "sacramento-rentals/1.0 (github.com/carolannejiang/sacramento-rentals)"
QUERY = f"""
[out:json][timeout:120];
(
  nwr["amenity"~"^(restaurant|cafe|bar|pub|fast_food|ice_cream|food_court|biergarten)$"]({BBOX});
  nwr["shop"]({BBOX});
  nwr["leisure"="park"]["name"]({BBOX});
  node["highway"="bus_stop"]({BBOX});
  node["railway"~"^(tram_stop|station)$"]({BBOX});
);
out center qt;
"""
GROCERY = {"supermarket", "grocery", "greengrocer", "health_food", "butcher", "deli", "farm"}


def kind(tags):
    if tags.get("amenity"):
        return "food"
    if tags.get("shop") in GROCERY:
        return "grocery"
    if tags.get("shop"):
        return "shop"
    if tags.get("leisure") == "park":
        return "park"
    return "transit"


def main():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    elements = None
    for attempt, server in enumerate(SERVERS * 2):  # public servers are often busy; try each twice
        try:
            req = urllib.request.Request(server, data=urllib.parse.urlencode({"data": QUERY}).encode(), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180, context=ctx) as r:
                elements = json.load(r)["elements"]
            break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  {server} failed ({e}); retrying")
            time.sleep(5 * (attempt + 1))
    if elements is None:
        sys.exit("All Overpass servers failed")
    rows = []
    for e in elements:
        lat, lon = (e["lat"], e["lon"]) if "lat" in e else (e.get("center", {}).get("lat"), e.get("center", {}).get("lon"))
        if lat is not None:
            rows.append([round(lat, 5), round(lon, 5), kind(e.get("tags", {}))])
    out = ROOT / "data/raw/places.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows))
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"{len(rows)} places", counts)


if __name__ == "__main__":
    main()
