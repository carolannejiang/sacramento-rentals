"""Convert data/raw/zillow.json into the shared listing schema at data/listings/zillow.json.

When data/raw/zillow_details.json has a listing's detail page, its facts and amenities become
`features` ({group: [items]}), and it fills in square footage, post date, pets and description.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNIT_TYPES = {"APARTMENT": "apartment", "CONDO": "condo", "TOWNHOUSE": "townhouse",
              "SINGLE_FAMILY": "house", "MULTI_FAMILY": "duplex"}


def num(s):
    m = re.search(r"\d[\d,.]*", str(s or ""))
    return float(m.group().replace(",", "")) if m else None


def human(s):
    """'MicrowaveOven' -> 'Microwave oven', 'SmallDogs' -> 'Small dogs'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s)).strip()
    return s[:1].upper() + s[1:].lower() if s.isascii() and " " in s and s == s.title() else s[:1].upper() + s[1:]


def items(*values):
    out = []
    for v in values:
        for i in (v if isinstance(v, list) else [v]):
            if i and str(i).lower() not in ("none", "unknown", "contact manager", "contact for details"):
                out.append(human(i))
    return list(dict.fromkeys(out))


# Building pages: yes/no amenities and the group they belong to.
BUILDING_FLAGS = {
    "hasSharedLaundry": ("Laundry", "Shared laundry"),
    "hasCeilingFan": ("In the unit", "Ceiling fan"), "hasPatioBalcony": ("In the unit", "Patio / balcony"),
    "hasFireplace": ("In the unit", "Fireplace"), "isFurnished": ("In the unit", "Furnished"),
    "hasStorage": ("In the unit", "Storage"),
    "hasSwimmingPool": ("Community", "Pool"), "hasHotTub": ("Community", "Hot tub"), "hasSauna": ("Community", "Sauna"),
    "hasPetPark": ("Community", "Pet park"), "hasBarbecue": ("Community", "Barbecue"), "hasElevator": ("Community", "Elevator"),
    "hasBicycleStorage": ("Community", "Bike storage"), "hasPackageService": ("Community", "Package service"),
    "hasValetTrash": ("Community", "Valet trash"),
    "hasOnsiteManagement": ("Building", "On-site management"), "hasTwentyFourHourMaintenance": ("Building", "24-hour maintenance"),
    "hasOnlineRentPayment": ("Building", "Online rent payment"), "hasOnlineMaintenancePortal": ("Building", "Online maintenance requests"),
    "hasDisabledAccess": ("Building", "Wheelchair accessible"), "isSmokeFree": ("Building", "Smoke-free"),
    "hasSpanishSpeakingStaff": ("Building", "Spanish-speaking staff"),
}


def building_features(b):
    f = {}
    add = lambda group, *vals: f.setdefault(group, []).extend(items(*vals))
    add("Cooling", b.get("airConditioning"))
    add("Heating", b.get("heatingSource"))
    add("Appliances", b.get("appliances"))
    add("Parking", b.get("parkingTypes"), b.get("parkingDescription"))
    pets = items(b.get("petPolicies"))
    for p in (b.get("detailedPetPolicy") or {}).get("petPolicies") or []:
        if p.get("allowed"):
            costs = [f"${p['deposit']:,} deposit" if p.get("deposit") else "", f"${p['monthlyFee']:,}/mo" if p.get("monthlyFee") else ""]
            if any(costs):
                pets.append(f"{human(p.get('petType', 'pets'))}: " + ", ".join(c for c in costs if c))
    add("Pets", pets)
    add("Flooring", b.get("floorCoverings"))
    add("In the unit", b.get("customUnitAmenities"))
    add("Community", b.get("communityRooms"), b.get("outdoorCommonAreas"), b.get("sportsCourts"), b.get("customPropertyAmenities"))
    add("Building", b.get("securityTypes"), b.get("viewType"))
    add("Utilities included", b.get("utilitiesIncluded"))
    for key, (group, label) in BUILDING_FLAGS.items():
        if b.get(key) is True:
            f.setdefault(group, []).append(label)
    fees = []
    if b.get("leaseLengths"):
        fees.append(f"Lease lengths: {b['leaseLengths']} months")
    if b.get("applicationFee"):
        fees.append(f"Application fee: ${b['applicationFee']}")
    if b.get("depositFeeMin"):
        lo, hi = b["depositFeeMin"], b.get("depositFeeMax") or b["depositFeeMin"]
        fees.append(f"Deposit: ${lo:,}" + (f"–${hi:,}" if hi != lo else ""))
    add("Lease & fees", fees)
    return f


def unit_features(r):
    f = {}
    add = lambda group, *vals: f.setdefault(group, []).extend(items(*vals))
    add("Laundry", r.get("laundryFeatures"))
    add("Cooling", r.get("cooling"))
    add("Heating", r.get("heating"))
    add("Appliances", r.get("appliances"))
    add("Parking", r.get("parkingFeatures"), r.get("otherParking"), "Garage" if r.get("hasGarage") else None,
        "Carport" if r.get("hasCarport") else None)
    add("Pets", r.get("allowedPets"))
    add("Flooring", r.get("flooring"))
    add("In the unit", r.get("interiorFeatures"), r.get("windowFeatures"), "Fireplace" if r.get("hasFireplace") else None,
        "Furnished" if r.get("furnished") else None)
    add("Outdoor", r.get("exteriorFeatures"), r.get("patioAndPorchFeatures"), r.get("fencing"), r.get("poolFeatures"))
    add("Community", r.get("communityFeatures"), r.get("associationAmenities"))
    add("Utilities included", r.get("utilities"))
    fees = [f"{d['type']}: {d['fee']}" for d in r.get("feesAndDues") or [] if d.get("fee")]
    if r.get("leaseTerm") and "contact" not in r["leaseTerm"].lower():
        fees.append(f"Lease: {r['leaseTerm']}")
    if r.get("yearBuilt"):
        fees.append(f"Built {r['yearBuilt']}")
    add("Lease & fees", fees)
    return f


COMPANY_WORDS = re.compile(r"management|mgmt|propert|realty|real estate|group|\binc\b|llc|corp|rentals|homes|investment|"
                           r"holdings|capital|services|\bDRE\b|residential|leasing|hemlane|doorstead|keyrenter|urbanhomes", re.I)


def lister(detail):
    """('company' | 'individual' | None, name). Apartment-building pages are always run by a company."""
    if detail.get("buildingAttributes"):
        return "company", None
    provider = detail.get("listingProvider") or {}
    name = (detail.get("broker") or {}).get("name") or provider.get("postingGroupName") or provider.get("agentName")
    if not name:
        return None, None
    return ("company" if COMPANY_WORDS.search(name) else "individual"), name


def convert(x, detail):
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
    listing = {
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
        "pets": None,  # from the detail page, below
        # Search results carry small "-p_e" thumbnails; "-cc_ft_960" is the 960px version.
        "photos": [p["url"].replace("-p_e.jpg", "-cc_ft_960.jpg") for p in (x.get("listingPhotos") or [])][:15],
        "description": f"Units: {unit_text}" if unit_text else None,
        "rentZestimate": x.get("rentZestimate"),
        "scamFlags": [],
    }
    if not detail:
        return listing

    reso, building = detail.get("resoFacts") or {}, detail.get("buildingAttributes") or {}
    features = building_features(building) if building else unit_features(reso)
    listing["features"] = {g: v for g, v in features.items() if v}
    listing["listedBy"], listing["listerName"] = lister(detail)
    offers = [o["description"].split("\n")[0] for o in detail.get("specialOffers") or []
              if o.get("description") and not o["description"].startswith("Total monthly leasing prices")]
    listing["specialOffer"] = offers[0] if offers else None
    if not listing["sqft"]:
        sizes = [p["livingArea"] for p in detail.get("listingFloorPlans") or []
                 if p.get("livingArea") and (beds is None or p.get("bedrooms") == beds)]
        listing["sqft"] = min(sizes) if sizes else None
    if not posted and reso.get("onMarketDate"):
        listing["postedAt"] = datetime.fromtimestamp(reso["onMarketDate"] / 1000, timezone.utc).isoformat()
    pets = listing["features"].get("Pets")
    if pets:
        # Zillow lists only the pets that are allowed, so a list without dogs means no dogs.
        listing["pets"] = "; ".join(pets) if any("dog" in p.lower() for p in pets) else f"No dogs ({', '.join(pets)} only)"
    if detail.get("description"):
        listing["description"] = ((listing["description"] + "\n\n") if listing["description"] else "") + detail["description"][:1500]
    return listing


def main():
    raw_path = ROOT / "data/raw/zillow.json"
    if not raw_path.exists():
        print("No Zillow search results yet")
        return
    details_path = ROOT / "data/raw/zillow_details.json"
    details = json.loads(details_path.read_text()) if details_path.exists() else {}
    raw = json.loads(raw_path.read_text())
    out = [convert(x, details.get(x["propertyUrl"])) for x in raw if x.get("listingStatus") == "forRent"]
    (ROOT / "data/listings/zillow.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(out)} Zillow listings, {sum(1 for x in out if x.get('features'))} with features")


if __name__ == "__main__":
    main()
