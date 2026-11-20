"""Pull median household income and the share of adults with a bachelor's degree for every
census tract around Sacramento, with tract boundaries, from Census Reporter (free, no key;
American Community Survey 5-year estimates) into data/raw/census_tracts.json.

Rows: {"name", "income", "bachelorsPct", "rings": [[[lon, lat], ...], ...]}
Usage: python3 scripts/fetch_census.py
"""
import json
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.censusreporter.org/1.0"
# Tracts in Sacramento, Yolo (West Sacramento) and Placer counties.
GEOS = "140|05000US06067,140|05000US06113,140|05000US06061"
UA = "sacramento-rentals/1.0 (github.com/carolannejiang/sacramento-rentals)"


def get_json(url):
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120, context=ctx) as r:
        return json.load(r)


def main():
    # B19013: median household income. B15003: education of adults 25+ (022-025: bachelor's or higher).
    data = get_json(f"{API}/data/show/latest?table_ids=B19013,B15003&geo_ids={GEOS}")
    shapes = get_json(f"{API}/geo/show/tiger2024?geo_ids={GEOS}")["features"]
    rows = []
    for f in shapes:
        d = data["data"].get(f["properties"]["geoid"])
        if not d:
            continue
        income = d["B19013"]["estimate"]["B19013001"]
        edu = d["B15003"]["estimate"]
        adults = edu["B15003001"]
        degree = sum(edu[f"B15003{n:03d}"] for n in range(22, 26))
        geom = f["geometry"]
        polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        rows.append({
            "name": f["properties"]["name"].split(",")[0],
            "income": round(income) if income else None,
            "bachelorsPct": round(100 * degree / adults) if adults else None,
            "rings": [p[0] for p in polygons],  # outer rings; tracts don't have holes worth handling
        })
    out = ROOT / "data/raw/census_tracts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"release": data["release"]["name"], "tracts": rows}))
    print(f"{len(rows)} census tracts from {data['release']['name']}")


if __name__ == "__main__":
    main()
