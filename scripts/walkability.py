"""What's within walking distance of each listing, from data/raw/places.json (fetch_places.py).

Adds `walk` to each listing with a map position:
  {"score": 0-100, "label": ..., "amenities": shops + restaurants within ~10 min walk,
   "food": .., "shops": .., "parks": .., "transit": stops within ~5 min, "groceryMi": nearest grocery}
Also writes site/places.json (shops and restaurants only) for the map's heatmap.

Score = amenities nearby (up to 60) + how close the nearest grocery is (up to 25)
        + transit stops nearby (up to 15).
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALK_M = 800      # ~10 minute walk
TRANSIT_M = 400   # ~5 minute walk
CELL = 0.01       # grid cell size in degrees (~1 km) for fast lookups
LABELS = [(70, "Very walkable"), (50, "Walkable"), (25, "Somewhat walkable"), (0, "Car-dependent")]


def meters(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_000
    dx = (lon2 - lon1) * 111_000 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def build_grid(places):
    grid = {}
    for lat, lon, kind in places:
        grid.setdefault((int(lat / CELL), int(lon / CELL)), []).append((lat, lon, kind))
    return grid


def nearby(grid, lat, lon, radius_cells):
    ci, cj = int(lat / CELL), int(lon / CELL)
    for i in range(ci - radius_cells, ci + radius_cells + 1):
        for j in range(cj - radius_cells, cj + radius_cells + 1):
            yield from grid.get((i, j), ())


def walk_info(grid, lat, lon):
    counts = {"food": 0, "shop": 0, "park": 0, "transit": 0}
    grocery = math.inf
    for plat, plon, kind in nearby(grid, lat, lon, 3):  # 3 cells covers the 1.5 mi grocery cap
        d = meters(lat, lon, plat, plon)
        if kind == "grocery":
            grocery = min(grocery, d)
            if d <= WALK_M:
                counts["shop"] += 1
        elif kind == "transit":
            counts["transit"] += d <= TRANSIT_M
        elif d <= WALK_M:
            counts[kind] += 1
    amenities = counts["food"] + counts["shop"]
    grocery_mi = grocery / 1609.34
    score = (60 * (1 - math.exp(-amenities / 40))
             + (25 if grocery_mi <= 0.3 else max(0, 25 * (1.5 - grocery_mi) / 1.2))
             + min(15, counts["transit"] * 3))
    score = round(score)
    return {
        "score": score,
        "label": next(label for cutoff, label in LABELS if score >= cutoff),
        "amenities": amenities, "food": counts["food"], "shops": counts["shop"],
        "parks": counts["park"], "transit": counts["transit"],
        "groceryMi": round(grocery_mi, 1) if grocery < math.inf else None,
    }


def add_walkability(listings):
    path = ROOT / "data/raw/places.json"
    if not path.exists():
        print("No places data yet; skipping walkability")
        return
    places = json.loads(path.read_text())
    grid = build_grid(places)
    scored = 0
    for x in listings:
        # Listings outside the area the places cover (e.g. Tahoe) get no score rather than a zero.
        if x.get("lat") is not None and next(nearby(grid, x["lat"], x["lon"], 3), None):
            x["walk"] = walk_info(grid, x["lat"], x["lon"])
            scored += 1
        else:
            x["walk"] = None
    heat = [[lat, lon] for lat, lon, kind in places if kind in ("food", "shop", "grocery")]
    (ROOT / "site/places.json").write_text(json.dumps(heat, separators=(",", ":")))
    print(f"Walkability for {scored} listings from {len(places)} places")
