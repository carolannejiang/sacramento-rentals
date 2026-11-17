"""Merge data/listings/*.json into data/all_listings.json and the public site/listings.json.

- Drops shared rooms, already-rented posts, and Facebook posts that fell out of the 30-day window.
- Collapses cross-posted duplicates: same source, same poster (or same title if no poster),
  same price, near-identical description. The kept record gets `alsoAt`: [{group, url}].
- Records when each listing was first seen (data/state.json) so the site can mark new ones.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_FIELDS = ("poster", "posterId")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())[:120]


def richness(x):
    return sum(v not in (None, "", [], {}) for v in x.values())


def main():
    rows = []
    for f in sorted((ROOT / "data/listings").glob("*.json")):
        rows += json.loads(f.read_text())

    # Facebook parse agents don't copy photo URLs; reattach them from the raw pull,
    # which also defines which posts are still inside the 30-day window.
    fb_raw = ROOT / "data/raw/facebook.json"
    photos = {}
    if fb_raw.exists():
        photos = {str(i.get("legacyId") or i.get("id")): [a["thumbnail"] for a in i.get("attachments") or [] if a.get("thumbnail")][:6]
                  for i in json.loads(fb_raw.read_text())}
    rows = [x for x in rows if x["source"] != "facebook" or str(x["sourceId"]) in photos]
    for x in rows:
        if x["source"] == "facebook" and not x.get("photos"):
            x["photos"] = photos.get(str(x["sourceId"]), [])

    # The user only wants whole units, never a room in a shared place.
    shared = [x for x in rows if x.get("unitType") == "room" or x.get("sharedSpace") is True]
    rented = [x for x in rows if "[RENTED]" in (x.get("title") or "").upper()]
    rows = [x for x in rows if x not in shared and x not in rented]
    print(f"Dropped {len(shared)} shared rooms/co-living rows and {len(rented)} already-rented rows")

    merged = {}
    for x in rows:
        key = (x["source"], x.get("posterId") or norm(x.get("title")), x.get("price"), norm(x.get("description")) or x["url"])
        if key not in merged:
            merged[key] = {**x, "alsoAt": []}
            continue
        kept = merged[key]
        copy = {"group": x.get("group"), "url": x["url"]}
        if richness(x) > richness(kept):
            copy = {"group": kept.get("group"), "url": kept["url"]}
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

    out = sorted(merged.values(), key=lambda x: x.get("postedAt") or x["firstSeen"], reverse=True)
    (ROOT / "data/all_listings.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    public = [{k: v for k, v in x.items() if k not in PRIVATE_FIELDS} for x in out]
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site/listings.json").write_text(json.dumps({"updatedAt": now, "listings": public}, ensure_ascii=False))

    by_source = {}
    for x in out:
        by_source[x["source"]] = by_source.get(x["source"], 0) + 1
    print(f"{len(rows)} rows -> {len(out)} listings", by_source)


if __name__ == "__main__":
    main()
