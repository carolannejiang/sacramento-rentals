"""Neighborhood numbers for each listing with an address and a map position.

Adds `area` to those listings:
  {"tract": census tract name, "income": median household income, "bachelorsPct": % of adults
   25+ with a bachelor's degree or higher (both from data/raw/census_tracts.json, fetch_census.py),
   "askingPsf": median asking $/sqft of homes for sale in the ZIP code (from the address, else the map position), "forSale": how many
   (data/raw/asking_psf.json, fetch_asking_prices.py),
   "rentPsf": median rent/sqft of current listings within half a mile, "rentComps": how many}
"""
import json
import re
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


def add_boxes(shapes):
    for t in shapes:
        t["boxes"] = [(min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r), max(p[1] for p in r)) for r in t["rings"]]


def find_shape(shapes, lat, lon):
    for t in shapes:
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
    add_boxes(tracts)
    path = ROOT / "data/raw/asking_psf.json"
    asking = json.loads(path.read_text()) if path.exists() else {"month": None, "zips": {}, "shapes": []}
    add_boxes(asking["shapes"])
    rents = build_grid([(x["lat"], x["lon"], x["price"] / x["sqft"]) for x in listings
                        if x.get("lat") is not None and x.get("price") and x.get("sqft") and not x.get("weeklyHotel")])
    counted = 0
    for x in listings:
        x["area"] = None
        if not x.get("address") or x.get("lat") is None:
            continue
        tract = find_shape(tracts, x["lat"], x["lon"])
        # Addresses sometimes give a PO box ZIP (no homes for sale); then use the map position's.
        zip_code = re.search(r"\b(9[0-6]\d{3})\b", x["address"])
        zip_code = zip_code.group(1) if zip_code else None
        if zip_code not in asking["zips"]:
            zip_code = (find_shape(asking["shapes"], x["lat"], x["lon"]) or {}).get("name")
        for_sale = asking["zips"].get(zip_code)
        rent_psf, n_rents = median_near(rents, x["lat"], x["lon"], MIN_RENTALS)
        area = {
            "tract": tract and tract["name"], "income": tract and tract["income"],
            "bachelorsPct": tract and tract["bachelorsPct"],
            "askingPsf": for_sale and for_sale[0], "forSale": for_sale and for_sale[1],
            "zip": zip_code,
            "rentPsf": rent_psf and round(rent_psf, 2), "rentComps": n_rents,
        }
        if tract or for_sale or rent_psf:
            x["area"] = area
            counted += 1
    print(f"Neighborhood stats for {counted} listings ({len(tracts)} census tracts)")
    return {"census": census and census["release"], "askingMonth": asking["month"]}
