"""Approximate areas for listings with no map position, from the places place_hints.py named.

The first place that OpenStreetMap can find becomes the listing's `approxArea`:
  {"label", "center": [lat, lon], and one of
   "polygon": [[lat, lon], ...]       neighborhood, town or ZIP outline,
   "lines": [[[lat, lon], ...], ...]  the stretch of a street,
   "radius": meters                   a circle around a landmark, cross streets or a place with no outline}
Lookups use Nominatim (1 request/second) and, for streets and cross streets, Overpass; results
are cached in data/work/area_cache.json.
"""
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from commute import UA, get_json, in_region

ROOT = Path(__file__).resolve().parent.parent
HINTS = ROOT / "data/work/place_hints.json"
CACHE = ROOT / "data/work/area_cache.json"
LOOKUPS_PER_RUN = 150
VIEWBOX = "-121.9,39.0,-120.9,38.2"  # commute.REGION as west, north, east, south
MAX_KM2 = 150  # bigger than this (all of Sacramento, say) says too little to draw
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
STOP = {"the", "of", "at", "and", "near", "ca", "california"}
# Common names that OpenStreetMap has no place for.
INFORMAL = {
    "natomas": (38.640, -121.505, 4500),
    "north natomas": (38.668, -121.508, 3000),
    "south natomas": (38.608, -121.500, 2200),
    "south sacramento": (38.488, -121.432, 5000),
}
RADIUS = {"building": 250, "intersection": 400, "neighborhood": 1200, "zip": 2500, "city": 3000}


def words(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - STOP


def km2(ring):
    """Area of a [[lat, lon], ...] ring (shoelace on a flat projection; fine at city scale)."""
    lat0 = math.radians(ring[0][0])
    pts = [(lon * 111.32 * math.cos(lat0), lat * 110.57) for lat, lon in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def meters(a, b):
    return math.hypot((a[0] - b[0]) * 111_000, (a[1] - b[1]) * 111_000 * math.cos(math.radians(a[0])))


def mean(points):
    return [round(sum(p[0] for p in points) / len(points), 5), round(sum(p[1] for p in points) / len(points), 5)]


def nominatim(**params):
    hits = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {**params, "format": "jsonv2", "countrycodes": "us", "viewbox": VIEWBOX, "bounded": 1, "limit": 5}))
    time.sleep(1.1)
    return hits


def overpass(query):
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    for server in OVERPASS:
        try:
            req = urllib.request.Request(server, data=urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
                return json.load(r)["elements"]
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  {server} failed ({e})")
    # Raised rather than returned so a busy server isn't cached as "not found".
    raise RuntimeError("all Overpass servers failed")


def outline(hit):
    """A Nominatim hit's outline as a [[lat, lon], ...] ring (its largest part), or None for a point."""
    g = hit.get("geojson") or {}
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") if g.get("type") == "MultiPolygon" else []
    rings = [[[round(lat, 5), round(lon, 5)] for lon, lat in p[0]] for p in polys]
    return max(rings, key=km2) if rings else None


def area_of(hit, label, radius):
    ring = outline(hit)
    if ring and km2(ring) > MAX_KM2:
        return None
    center = [round(float(hit["lat"]), 5), round(float(hit["lon"]), 5)]
    return {"label": label, "center": center, "polygon": ring} if ring else {"label": label, "center": center, "radius": radius}


def find_street(name, city):
    hits = nominatim(street=name, city=city or "Sacramento", state="CA")
    return next((h for h in hits if h["category"] == "highway" and words(name) <= words(h["name"])), None)


def locate(p):
    kind, name, city = p["kind"], p["name"].replace('"', "").strip(), p.get("city")
    where = f"{name}, {city or 'Sacramento'}, CA"
    if kind in ("neighborhood", "city"):
        if name.lower() in INFORMAL:
            lat, lon, r = INFORMAL[name.lower()]
            return {"label": name, "center": [lat, lon], "radius": r}
        if words(name) <= {"sacramento"}:
            return None
        hits = nominatim(q=where if kind == "neighborhood" else f"{name}, CA", featureType="settlement",
                         polygon_geojson=1, polygon_threshold=0.0005)
        hit = next((h for h in hits if words(name) <= words(h["name"])), None)
        return hit and area_of(hit, name, RADIUS[kind])
    if kind == "zip":
        if not re.fullmatch(r"\d{5}", name):
            return None
        hits = nominatim(postalcode=name, country="us", polygon_geojson=1, polygon_threshold=0.0005)
        return area_of(hits[0], f"ZIP {name}", RADIUS["zip"]) if hits else None
    if kind in ("building", "landmark"):
        hits = nominatim(q=where)
        # The full name must match: "Gold Ridge Apartments" is not "Gold Ridge Elementary School".
        hit = next((h for h in hits if h["category"] != "highway" and words(name) <= words(h["name"])), None)
        if not hit:
            return None
        s, n, w, e = map(float, hit["boundingbox"])
        size = meters((s, w), (n, e)) / 2  # a campus or park is bigger than a building
        return {"label": f"Near {hit['name']}", "center": [round(float(hit["lat"]), 5), round(float(hit["lon"]), 5)],
                "radius": round(max(RADIUS["building"] if kind == "building" else 600, size + 300))}
    street = find_street(name, city)
    if not street:
        return None
    anchor = f"(around:{8000 if kind == 'intersection' else 2500},{street['lat']},{street['lon']})"
    if kind == "intersection":
        cross = (p.get("crossStreet") or "").replace('"', "").strip()
        if not cross:
            return None
        nodes = overpass(f'[out:json][timeout:60];way["highway"]["name"="{street["name"]}"]{anchor}->.a;'
                         f'way["highway"]["name"="{cross}"]{anchor}->.b;node(w.a)(w.b);out;')
        points = [(e["lat"], e["lon"]) for e in nodes]
        if not points:
            return None
        center = mean(points)
        if max(meters(center, q) for q in points) > 800:  # two different places with these street names
            return None
        return {"label": f"Near {street['name']} & {cross}", "center": center, "radius": RADIUS["intersection"]}
    ways = overpass(f'[out:json][timeout:60];way["highway"]["name"="{street["name"]}"]{anchor};out geom;')
    lines = [[[round(g["lat"], 5), round(g["lon"], 5)] for g in w["geometry"]] for w in ways]
    if not lines:
        return None
    return {"label": f"On {street['name']}", "center": mean([q for line in lines for q in line]), "lines": lines}


def add_approx_areas(listings):
    hints = json.loads(HINTS.read_text()) if HINTS.exists() else {}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    looked_up = found = 0
    for x in listings:
        x["approxArea"] = None
        if x.get("lat") is not None:
            continue
        for p in hints.get(x["id"]) or []:
            key = json.dumps([p["kind"], p["name"], p.get("crossStreet"), p.get("city")])
            if key not in cache:
                if looked_up >= LOOKUPS_PER_RUN:
                    break
                try:
                    cache[key] = locate(p)
                except Exception as e:
                    print(f"  area lookup failed for {key}: {e}")
                    continue
                looked_up += 1
            if cache[key] and in_region(*cache[key]["center"]):
                x["approxArea"] = cache[key]
                found += 1
                break
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))
    print(f"Approximate areas for {found} listings without an exact position ({looked_up} new lookups)")
