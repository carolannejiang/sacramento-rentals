"""Neighborhood numbers for each listing with an address and a map position.

Adds `area` to those listings:
  {"tract": census tract name, "income": median household income, "bachelorsPct": % of adults
   25+ with a bachelor's degree or higher (both from data/raw/census_tracts.json, fetch_census.py),
   "rentPsf": median rent/sqft of current listings within half a mile, "rentComps": how many}
"""
import json
import statistics
from pathlib import Path

from walkability import build_grid, meters, nearby

ROOT = Path(__file__).resolve().parent.parent
RADIUS_M = 800      # half a mile
MIN_RENTALS = 5


def inside(lon, lat, ring):
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def find_tract(tracts, lat, lon):
    for t in tracts:
        if any(r[0] <= lon <= r[2] and r[1] <= lat <= r[3] and inside(lon, lat, ring)
               for ring, r in zip(t["rings"], t["boxes"])):
            return t
    return None


def median_near(grid, lat, lon, minimum):
    # 1 cell (~1 km) covers the half-mile radius
    values = [v for plat, plon, v in nearby(grid, lat, lon, 1) if meters(lat, lon, plat, plon) <= RADIUS_M]
    return (statistics.median(values), len(values)) if len(values) >= minimum else (None, len(values))


def add_area_stats(listings):
    path = ROOT / "data/raw/census_tracts.json"
    census = json.loads(path.read_text()) if path.exists() else None
    tracts = census["tracts"] if census else []
    for t in tracts:
        t["boxes"] = [(min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r), max(p[1] for p in r)) for r in t["rings"]]
    rents = build_grid([(x["lat"], x["lon"], x["price"] / x["sqft"]) for x in listings
                        if x.get("lat") is not None and x.get("price") and x.get("sqft") and not x.get("weeklyHotel")])
    counted = 0
    for x in listings:
        x["area"] = None
        if not x.get("address") or x.get("lat") is None:
            continue
        tract = find_tract(tracts, x["lat"], x["lon"])
        rent_psf, n_rents = median_near(rents, x["lat"], x["lon"], MIN_RENTALS)
        area = {
            "tract": tract and tract["name"], "income": tract and tract["income"],
            "bachelorsPct": tract and tract["bachelorsPct"],
            "rentPsf": rent_psf and round(rent_psf, 2), "rentComps": n_rents,
        }
        if tract or rent_psf:
            x["area"] = area
            counted += 1
    print(f"Neighborhood stats for {counted} listings ({len(tracts)} census tracts)")
    return census and census["release"]
