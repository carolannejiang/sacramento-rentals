"""Pull the median asking price per square foot of homes for sale in each California ZIP code
from Realtor.com's public research data (monthly) into data/raw/asking_psf.json, with ZIP
boundaries around Sacramento from Census Reporter for listings whose address has no ZIP.

These are list prices, not sale prices: Redfin's sold-homes data isn't reachable without
getting past its bot check.
Rows: {"month": "2026-10", "zips": {"95816": [$/sqft, homes for sale], ...},
       "shapes": [{"name": "95816", "rings": [[[lon, lat], ...]]}, ...]}
Usage: python3 scripts/fetch_asking_prices.py
"""
import csv
import io
import json
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Zip.csv"
# ZIP code areas in Sacramento, Yolo (West Sacramento) and Placer counties.
SHAPES = "https://api.censusreporter.org/1.0/geo/show/tiger2024?geo_ids=860|05000US06067,860|05000US06113,860|05000US06061"
UA = "sacramento-rentals/1.0 (github.com/carolannejiang/sacramento-rentals)"


def main():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=120, context=ctx) as r:
        rows = list(csv.DictReader(io.TextIOWrapper(r, encoding="utf-8")))
    zips, month = {}, None
    for x in rows:
        if x["zip_name"].endswith(", ca") and x["median_listing_price_per_square_foot"]:
            zips[x["postal_code"].zfill(5)] = [round(float(x["median_listing_price_per_square_foot"])),
                                                int(float(x["active_listing_count"] or 0))]
            month = f"{x['month_date_yyyymm'][:4]}-{x['month_date_yyyymm'][4:]}"
    with urllib.request.urlopen(urllib.request.Request(SHAPES, headers={"User-Agent": UA}), timeout=120, context=ctx) as r:
        features = json.load(r)["features"]
    shapes = [{"name": f["properties"]["name"],
               "rings": [p[0] for p in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon"
                                        else [f["geometry"]["coordinates"]])]} for f in features]
    out = ROOT / "data/raw/asking_psf.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"month": month, "zips": zips, "shapes": shapes}))
    print(f"Asking $/sqft for {len(zips)} California ZIP codes ({month}), {len(shapes)} ZIP boundaries")


if __name__ == "__main__":
    main()
