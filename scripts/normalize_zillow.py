"""Convert data/raw/zillow.json into the shared listing schema at data/listings/zillow.json."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNIT_TYPES = {"APARTMENT": "apartment", "CONDO": "condo", "TOWNHOUSE": "townhouse",
              "SINGLE_FAMILY": "house", "MULTI_FAMILY": "duplex"}


def num(s):
    m = re.search(r"\d[\d,.]*", str(s or ""))
    return float(m.group().replace(",", "")) if m else None


def convert(x):
    units = x.get("units") or []
    # Buildings list one row per floor plan; headline the smallest plan so price and beds match.
    plans = sorted((num(u.get("beds")) or 0, num(u.get("price"))) for u in units if num(u.get("price")))
    price = (x.get("listingPrice") or {}).get("amount") or (plans[0][1] if plans else None)
    beds = x.get("bedrooms") if x.get("bedrooms") is not None else (plans[0][0] if plans else None)
    addr = x.get("listingAddress") or {}
    full = addr.get("full") or ""
    name = full.split(",")[0] if full and not full[0].isdigit() else addr.get("street")
    posted = None
    if x.get("daysOnZillow") is not None and x.get("scrapedAt"):
        posted = (datetime.fromisoformat(x["scrapedAt"].replace("Z", "+00:00")) - timedelta(days=x["daysOnZillow"])).isoformat()
    unit_text = "; ".join(f"{u.get('beds')} bd from {u.get('price')}" for u in units)
    coords = x.get("coordinates") or {}
    return {
        "source": "zillow",
        "sourceId": str(x["zpid"]),
        "url": x["propertyUrl"],
        "postedAt": posted,
        "title": name,
        "price": price,
        "beds": beds,
        "baths": x.get("bathrooms"),
        "sqft": x.get("livingArea"),
        "unitType": UNIT_TYPES.get(x.get("homeType"), "apartment"),
        "neighborhood": None,
        "address": full or None,
        "lat": coords.get("latitude"),
        "lon": coords.get("longitude"),
        "moveIn": (x.get("availabilityDate") or "")[:10] or None,
        "pets": "Small dogs OK (Zillow search filter)",
        "photos": [p["url"] for p in (x.get("listingPhotos") or [])][:6],
        "description": f"Units: {unit_text}" if unit_text else None,
        "rentZestimate": x.get("rentZestimate"),
        "scamFlags": [],
    }


def main():
    raw = json.loads((ROOT / "data/raw/zillow.json").read_text())
    out = [convert(x) for x in raw if x.get("listingStatus") == "forRent"]
    (ROOT / "data/listings/zillow.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(out)} Zillow listings")


if __name__ == "__main__":
    main()
