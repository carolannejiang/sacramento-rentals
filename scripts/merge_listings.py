"""Merge data/listings/*.json into data/all_listings.json and the public site/listings.json.

- Drops shared rooms, already-rented posts, and Facebook posts that fell out of the 30-day window.
- Collapses cross-posted duplicates: same source, same price, near-identical description,
  and (outside Facebook) same title. The kept record gets `alsoAt`: [{group, url}].
- Records when each listing was first seen (data/state.json) so the site can mark new ones.
- Adds map positions from addresses and drive times to sources/destinations.json (commute.py),
  what's within walking distance (walkability.py), and neighborhood income, degrees,
  asking price per sqft and rent per sqft (area_stats.py).
- Listings still without a position get the general area they describe (approx_area.py).
"""
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from area_stats import add_area_stats
from approx_area import add_approx_areas
from commute import add_commutes, geocode_missing
from walkability import add_walkability

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_FIELDS = ("poster", "posterId", "contact")
PHONE_OR_EMAIL = re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+")


def public(x):
    """The listing without who posted it. Facebook posts come from private people, so their
    phone numbers and emails are also taken out of the text."""
    out = {k: v for k, v in x.items() if k not in PRIVATE_FIELDS}
    if "facebook" in (x.get("sources") or [x["source"]]) and out.get("description"):
        out["description"] = PHONE_OR_EMAIL.sub("[contact removed]", out["description"])
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())[:120]


def richness(x):
    return sum(v not in (None, "", [], {}) for v in x.values())


# ---- the same unit listed on more than one platform ----
# Pick the copy to show by source (most structured first) so a listing's id, and with it
# the viewer's saved/hidden state, stays stable between runs.
SOURCE_RANK = {"zillow": 0, "redfin": 1, "craigslist": 2, "facebook": 3}


def address_key(addr):
    """'1523 Los Robles Blvd Apt 4, Sacramento' -> ('1523', 'losrobles', '4')."""
    a = (addr or "").lower().split(",")[0]
    m = re.match(r"\s*(\d+)\s+(?:[nsew]\.?\s+)?([a-z0-9]+(?:\s+[a-z0-9]+)?)", a)
    if not m:
        return None
    street = re.sub(r"\s+(st|street|ave|avenue|blvd|dr|drive|way|rd|road|ln|lane|ct|court|cir|pl|pkwy)$", "", m.group(2))
    unit = re.search(r"(?:apt|unit|#)\s*([a-z0-9-]+)", a)
    return m.group(1), street.replace(" ", ""), unit.group(1) if unit else None


def close_price(a, b, tolerance):
    return a is None or b is None or abs(a - b) <= tolerance * max(a, b)


def meters(a, b):
    dlat = (a["lat"] - b["lat"]) * 111_000
    dlon = (a["lon"] - b["lon"]) * 111_000 * math.cos(math.radians(a["lat"]))
    return math.hypot(dlat, dlon)


def repost(a, b, ka, kb):
    """Same platform, same unit posted again under a new title (often with a price drop)."""
    if not (ka and kb and ka == kb and a.get("beds") is not None and a.get("beds") == b.get("beds")):
        return False
    # Exact match, not "same or missing": a post without sqft would otherwise chain together
    # every floor plan in a big building.
    if a.get("baths") != b.get("baths") or a.get("sqft") != b.get("sqft"):
        return False
    same_text = norm(a.get("description"))[:100] == norm(b.get("description"))[:100] != ""
    return same_text or close_price(a.get("price"), b.get("price"), 0.15)


def same_unit(a, b):
    ka, kb = address_key(a.get("address")), address_key(b.get("address"))
    if a["source"] == b["source"]:
        return repost(a, b, ka, kb)
    if a.get("beds") is not None and b.get("beds") is not None and a["beds"] != b["beds"]:
        return False
    if ka and kb and ka[:2] == kb[:2] and (ka[2] is None or kb[2] is None or ka[2] == kb[2]):
        return close_price(a.get("price"), b.get("price"), 0.10)
    # No usable address on one side: need the same spot on the map, same beds, near-identical rent.
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"), a.get("beds"), a.get("price"), b.get("price")):
        return False
    return meters(a, b) <= 75 and close_price(a["price"], b["price"], 0.03)


def merge_across_sources(listings):
    parent = list(range(len(listings)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            if same_unit(listings[i], listings[j]):
                parent[find(i)] = find(j)

    groups = {}
    for i, x in enumerate(listings):
        groups.setdefault(find(i), []).append(x)
    out = []
    for members in groups.values():
        # Show the newest post from the best source (reposts often drop the price), but keep the id
        # of the first one seen so saved/hidden/contacted marks survive a repost.
        members.sort(key=lambda x: (SOURCE_RANK.get(x["source"], 9), x.get("postedAt") or x["firstSeen"]), reverse=False)
        best_rank = SOURCE_RANK.get(members[0]["source"], 9)
        newest = max((m for m in members if SOURCE_RANK.get(m["source"], 9) == best_rank),
                     key=lambda x: (x.get("postedAt") or x["firstSeen"], richness(x)))
        members.remove(newest)
        members.insert(0, newest)
        oldest = min(members, key=lambda x: (x["firstSeen"], x["id"]))
        primary = {**members[0], "alsoAt": list(members[0]["alsoAt"]), "id": oldest["id"]}
        for other in members[1:]:
            primary["alsoAt"].append({"source": other["source"], "group": other.get("group"), "url": other["url"]})
            primary["alsoAt"] += other["alsoAt"]
            for field in ("address", "lat", "lon", "baths", "sqft", "pets", "moveIn", "description", "neighborhood",
                          "listedBy", "listerName"):
                if primary.get(field) in (None, "") and other.get(field) not in (None, ""):
                    primary[field] = other[field]
            if not primary.get("photos"):
                primary["photos"] = other.get("photos") or []
            primary["scamFlags"] = sorted(set(primary.get("scamFlags") or []) | set(other.get("scamFlags") or []))
            primary["firstSeen"] = min(primary["firstSeen"], other["firstSeen"])
        primary["sources"] = sorted({m["source"] for m in members}, key=lambda s: SOURCE_RANK.get(s, 9))
        primary["reposts"] = sum(1 for m in members if m["source"] == primary["source"]) - 1
        out.append(primary)
    return out


def main():
    rows = []
    for f in sorted((ROOT / "data/listings").glob("*.json")):
        rows += json.loads(f.read_text())

    # Facebook parse agents don't copy photo URLs; reattach them from the raw pull,
    # which also defines which posts are still inside the 30-day window.
    fb_raw = ROOT / "data/raw/facebook.json"
    photos = {}
    if fb_raw.exists():
        photos = {str(i.get("legacyId") or i.get("id")): [a["thumbnail"] for a in i.get("attachments") or [] if a.get("thumbnail")][:15]
                  for i in json.loads(fb_raw.read_text())}
    rows = [x for x in rows if x["source"] != "facebook" or str(x["sourceId"]) in photos]
    for x in rows:
        if x["source"] == "facebook":
            x["photos"] = photos.get(str(x["sourceId"])) or x.get("photos") or []

    # Who posted Craigslist/Facebook listings (classify_lister.py); Zillow sets this itself.
    lister_path = ROOT / "data/work/lister_cache.json"
    listers = json.loads(lister_path.read_text()) if lister_path.exists() else {}
    for x in rows:
        hit = listers.get(f"{x['source']}:{x['sourceId']}")
        if hit:
            x["listedBy"] = hit["listedBy"] if hit["listedBy"] != "unknown" else None
            x["listerName"] = hit.get("company")

    # The user only wants whole units, never a room in a shared place.
    shared = [x for x in rows if x.get("unitType") == "room" or x.get("sharedSpace") is True]
    rented = [x for x in rows if "[RENTED]" in (x.get("title") or "").upper()]
    rows = [x for x in rows if x not in shared and x not in rented]
    print(f"Dropped {len(shared)} shared rooms/co-living rows and {len(rented)} already-rented rows")

    merged = {}
    for x in rows:
        # Facebook cross-posts share text but get different titles from the sorter; other
        # sources reuse boilerplate text across distinct units, so they also match on title.
        title = "" if x["source"] == "facebook" else norm(x.get("title"))
        key = (x["source"], title, x.get("price"), norm(x.get("description")) or norm(x.get("title")) or x["url"])
        if key not in merged:
            merged[key] = {**x, "alsoAt": []}
            continue
        kept = merged[key]
        copy = {"source": x["source"], "group": x.get("group"), "url": x["url"]}
        if richness(x) > richness(kept):
            copy = {"source": kept["source"], "group": kept.get("group"), "url": kept["url"]}
            merged[key] = {**x, "alsoAt": kept["alsoAt"]}
        merged[key]["alsoAt"].append(copy)

    state_path = ROOT / "data/state.json"
    first_seen = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for x in merged.values():
        x["id"] = f"{x['source']}:{x['sourceId']}"
        x["firstSeen"] = first_seen.setdefault(x["id"], now)
        x["weeklyHotel"] = bool(re.search(r"\bweekly\b|extended stay", x.get("title") or "", re.I))
    state_path.write_text(json.dumps(first_seen))

    geocode_missing(list(merged.values()))
    combined = merge_across_sources(list(merged.values()))
    print(f"Folded {len(merged) - len(combined)} reposts and cross-platform copies into the same unit")
    add_approx_areas(combined)
    destinations = add_commutes(combined)
    add_walkability(combined)
    sources = add_area_stats(combined)
    out = sorted(combined, key=lambda x: x.get("postedAt") or x["firstSeen"], reverse=True)
    (ROOT / "data/all_listings.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site/listings.json").write_text(json.dumps(
        {"updatedAt": now, "destinations": destinations, **sources, "listings": [public(x) for x in out]}, ensure_ascii=False))

    by_source = {}
    for x in out:
        by_source[x["source"]] = by_source.get(x["source"], 0) + 1
    print(f"{len(rows)} rows -> {len(out)} listings", by_source)


if __name__ == "__main__":
    main()
