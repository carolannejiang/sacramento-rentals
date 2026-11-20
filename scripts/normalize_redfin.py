"""Convert data/raw/redfin.json (+ data/raw/redfin_details/) into data/listings/redfin.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT_TYPES = {5: "apartment", 6: "house", 3: "townhouse", 2: "condo", 4: "duplex"}
# Property-management software feeds vs. tools small landlords use to list their own place.
COMPANY_FEEDS = {"APPFOLIO_FREE", "APPFOLIO_MERGE", "BUILDIUM", "TENANTTURNER2", "SHOWMOJO", "RENTLY", "TRICON",
                 "RENTENGINELISTINGS", "HEROPM", "HEMLANE", "ZIPRENT", "RENTEC", "RENTALBEAST"}
INDIVIDUAL_FEEDS = {"REDFIN_DIY", "TURBOTENANT", "AVAIL"}


def photos(rental_id, info):
    # Same numbering Redfin's own page uses; genMid is the ~620px version.
    return [f"https://ssl.cdn-redfin.com/photo/rent/{rental_id}/mbphoto/genMid.{pos}_{r['version']}.jpg"
            for r in (info or {}).get("photoRanges", []) for pos in range(r["startPos"], r["endPos"] + 1)][:15]


def floor_plans(plans):
    """('Studio from $1,450; 2 Bed from $2,025', ['Deposit: $500', 'Lease: 12 months'])"""
    # Bedroom groups with nothing available only have "unavailableUnitTypes".
    groups = [(g["bedroomTitle"], g.get("availableUnitTypes") or [])
              for g in (plans or {}).get("unitTypesByBedroom") or [] if g["bedroomTitle"] != "All"]
    lines, fees = [], []
    for title, types in groups:
        prices = [t["rentPriceMin"] for t in types if t.get("rentPriceMin")]
        if prices:
            lines.append(f"{title} from ${min(prices):,}")
    types = [t for _, ts in groups for t in ts]
    deposits = sorted({t["deposit"] for t in types if t.get("deposit")})
    if deposits:
        fees.append(f"Deposit: ${deposits[0]:,}" + (f"–${deposits[-1]:,}" if len(deposits) > 1 else ""))
    terms = sorted({t.replace("Available months ", "") for x in types for t in x.get("availableLeaseTerms") or []})
    if terms:
        fees.append(f"Lease: {', '.join(terms)} months")
    return "; ".join(lines), fees


def convert(h, detail):
    home, r = h["homeData"], h["rentalExtension"]
    addr = home.get("addressInfo") or {}
    point = (addr.get("centroid") or {}).get("centroid") or {}
    low = lambda key: (r.get(key) or {}).get("min")
    name = r.get("propertyName") or addr.get("formattedStreetLine")
    amen = detail.get("amenities") or {}
    units, fees = floor_plans(detail.get("floorPlans"))
    pet_friendly = "Pet Friendly" in (amen.get("communityAmenities") or []) + (amen.get("standardizedAmenities") or [])
    features = {
        "In the unit": amen.get("unitAmenities") or [],
        "Community": [a for a in amen.get("communityAmenities") or [] if a != "Pet Friendly"],
        "Other": amen.get("otherAmenities") or [],
        "Pets": ["Dogs allowed"] if h["dogsAllowed"] else ["Pet friendly"] if pet_friendly else [],
        "Lease & fees": fees,
    }
    feed = r.get("feedSource")
    if feed in COMPANY_FEEDS or home.get("propertyType") == 5 or (r.get("numAvailableUnits") or 0) > 1:
        listed_by = "company"
    else:
        listed_by = "individual" if feed in INDIVIDUAL_FEEDS else None
    text = (r.get("description") or "").strip()
    return {
        "source": "redfin",
        "sourceId": home["propertyId"],
        "url": "https://www.redfin.com" + home["url"],
        "postedAt": None,  # Redfin's API has no listing date; the site falls back to first seen
        "title": name,
        "price": low("rentPriceRange"),
        "beds": low("bedRange"),
        "baths": low("bathRange"),
        "sqft": low("sqftRange"),
        "unitType": UNIT_TYPES.get(home.get("propertyType"), "other"),
        "neighborhood": None,
        "address": ", ".join(p for p in (addr.get("formattedStreetLine"), addr.get("city"),
                                         f"{addr.get('state', '')} {addr.get('zip', '')}".strip()) if p) or None,
        "lat": point.get("latitude"),
        "lon": point.get("longitude"),
        "moveIn": (r.get("dateAvailable") or "")[:10] or None,
        "pets": "Dogs allowed (Redfin filter)" if h["dogsAllowed"] else "Pet friendly" if pet_friendly else None,
        "photos": photos(r["rentalId"], home.get("photosInfo")),
        "description": "\n\n".join(p for p in (f"Units: {units}" if units else "", text) if p) or None,
        "features": {g: v for g, v in features.items() if v},
        "listedBy": listed_by,
        "listerName": None,
        "specialOffer": next((s["sashTypeName"].capitalize() for s in home.get("sashes") or []
                              if "FREE" in s["sashTypeName"] or "SPECIAL" in s["sashTypeName"]), None),
        "scamFlags": [],
    }


def main():
    raw_path = ROOT / "data/raw/redfin.json"
    if not raw_path.exists():
        print("No Redfin search results yet")
        return
    details = ROOT / "data/raw/redfin_details"
    out = []
    for h in json.loads(raw_path.read_text()):
        path = details / f"{h['rentalExtension']['rentalId']}.json"
        out.append(convert(h, json.loads(path.read_text()) if path.exists() else {}))
    (ROOT / "data/listings/redfin.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(out)} Redfin listings, {sum(1 for x in out if x['features'].get('In the unit'))} with amenities")


if __name__ == "__main__":
    main()
