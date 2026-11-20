"""Map positions and drive times for listings.

- geocode_missing: listings with a street address but no map position get one from
  OpenStreetMap's Nominatim (free, 1 request/second, results cached).
- add_commutes: driving time and distance from each listing to every place in
  sources/destinations.json, from the public OSRM router (free, no traffic, cached by
  position). Where routing fails, the straight-line distance is used instead.
Caches live in data/work/ so each listing is only looked up once.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEOCODE_CACHE = ROOT / "data/work/geocode_cache.json"
ROUTE_CACHE = ROOT / "data/work/route_cache.json"
UA = "sacramento-rentals/1.0 (github.com/carolannejiang/sacramento-rentals)"
GEOCODE_PER_RUN = 150
REGION = (38.2, 39.0, -121.9, -120.9)  # lat min/max, lon min/max around Sacramento
UNIT = re.compile(r",?\s*(?:#|\b(?:apt|unit|ste|suite)\b\.?)\s*[\w-]+", re.I)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.load(r)


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def in_region(lat, lon):
    return REGION[0] <= lat <= REGION[1] and REGION[2] <= lon <= REGION[3]


def geocode_missing(listings):
    cache = load(GEOCODE_CACHE)
    looked_up = found = 0
    for x in listings:
        addr = (x.get("address") or "").strip()
        if x.get("lat") is not None or not re.search(r"\d+\s+\w", addr):
            continue
        query = addr if re.search(r"sacramento|, ca\b|california|\d{5}", addr, re.I) else f"{addr}, Sacramento, CA"
        if cache.get(query, 0) is None:  # not found as written; unit numbers ("APT 335", "#7") often trip it up
            query = UNIT.sub("", query)
        if query not in cache:
            if looked_up >= GEOCODE_PER_RUN:
                continue
            try:
                hits = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                    {"q": query, "format": "json", "limit": 1, "countrycodes": "us"}))
                cache[query] = [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None
            except Exception as e:
                print(f"  geocode failed for {query!r}: {e}")
                continue
            looked_up += 1
            time.sleep(1.1)
        if cache.get(query) and in_region(*cache[query]):
            x["lat"], x["lon"] = cache[query]
            found += 1
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE.write_text(json.dumps(cache))
    print(f"Geocoded {found} listings from their address ({looked_up} new lookups)")


def straight_miles(a_lat, a_lon, b_lat, b_lon):
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def add_commutes(listings):
    dests = json.loads((ROOT / "sources/destinations.json").read_text())
    cache = load(ROUTE_CACHE)
    sig = ";".join(f"{d['lon']},{d['lat']}" for d in dests)
    if cache.get("_destinations") != sig:  # destinations changed: old drive times are stale
        cache = {"_destinations": sig}
    key = lambda x: f"{x['lat']:.4f},{x['lon']:.4f}"
    todo = sorted({key(x) for x in listings if x.get("lat") is not None and key(x) not in cache})
    for n in range(0, len(todo), 90):
        batch = todo[n:n + 90]
        coords = sig + ";" + ";".join(f"{k.split(',')[1]},{k.split(',')[0]}" for k in batch)
        sources = ";".join(str(i + len(dests)) for i in range(len(batch)))
        targets = ";".join(str(i) for i in range(len(dests)))
        try:
            r = get_json(f"https://router.project-osrm.org/table/v1/driving/{coords}"
                         f"?sources={sources}&destinations={targets}&annotations=duration,distance")
            for k, secs, meters in zip(batch, r["durations"], r["distances"]):
                cache[k] = [[s, m] for s, m in zip(secs, meters)]
        except Exception as e:
            print(f"  routing failed for a batch of {len(batch)}: {e}")
        time.sleep(1)
    ROUTE_CACHE.write_text(json.dumps(cache))

    routed = 0
    for x in listings:
        if x.get("lat") is None:
            x["commute"] = None
            continue
        legs = cache.get(key(x))
        x["commute"] = {}
        for i, d in enumerate(dests):
            if legs and legs[i][0] is not None:
                x["commute"][d["id"]] = {"min": round(legs[i][0] / 60), "mi": round(legs[i][1] / 1609.34, 1)}
            else:
                x["commute"][d["id"]] = {"mi": round(straight_miles(x["lat"], x["lon"], d["lat"], d["lon"]), 1), "straightLine": True}
        routed += bool(legs)
    print(f"Drive times for {routed} listings ({len(todo)} new positions routed)")
    return dests
