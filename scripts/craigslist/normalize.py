"""Build raw + normalized Craigslist listing JSON from the sapi search responses and cached detail pages.
Usage: python3 -I normalize.py <search_dir> <details_dir> <raw_out> <listings_out>
"""
import glob, html, json, os, re, statistics, sys
from datetime import datetime, timezone, date

search_dir, det_dir, raw_out, out_path = sys.argv[1:5]
responses = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(search_dir, "*.json")))]


def img_url(code):  # "3:00909_lY6GzZWjntn_0k70kl" -> images.craigslist.org/00909_lY6GzZWjntn_0k70kl_600x450.jpg
    return f"https://images.craigslist.org/{code.split(':', 1)[-1]}_600x450.jpg"


def text_of(fragment):
    s = re.sub(r"<br\s*/?>", "\n", fragment)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def parse_detail(s):
    out = {}
    m = re.search(r'id="ld_posting_data"\s*>(.*?)</script>', s, re.S)
    if m:
        try:
            out["ld"] = json.loads(m.group(1))
        except ValueError:
            pass
    m = re.search(r'id="map"[^>]*data-latitude="([-\d.]+)"[^>]*data-longitude="([-\d.]+)"(?:[^>]*data-accuracy="(\d+)")?', s)
    if m:
        out["map"] = {"lat": float(m.group(1)), "lon": float(m.group(2)), "accuracy": m.group(3)}
    m = re.search(r'<div class="mapaddress">(.*?)</div>', s, re.S)
    if m:
        out["mapaddress"] = text_of(m.group(1))
    attrs = []
    # each attr is a span.attr or div.attr; collect class + text
    for cls, body in re.findall(r'<(?:span|div) class="(attr(?:\s[^"]*)?)">(.*?)</(?:span|div)>\s*(?=<(?:span|div) class="attr|</div>)', s, re.S):
        attrs.append({"class": cls, "text": text_of(body)})
    out["attrs"] = attrs
    m = re.search(r'<section id="postingbody">(.*?)</section>', s, re.S)
    if m:
        body = re.sub(r'<div class="print-information.*?</div>\s*</div>', "", m.group(1), flags=re.S)
        out["body"] = text_of(body)
    times = re.findall(r'<p class="postinginfo reveal">\s*(posted|updated):\s*<time[^>]*datetime="([^"]+)"', s)
    out["times"] = {k: v for k, v in times}
    out["thumbs"] = list(dict.fromkeys(re.findall(r'https://images\.craigslist\.org/[A-Za-z0-9_]+_600x450\.jpg', s)))
    if re.search(r"This posting has been (deleted|flagged|expired)", s):
        out["removed"] = True
    return out


# ---- raw search records ----
records = []
seen_ids = set()
# Each response has its own decode table (id/date offsets, location names).
for item, dec in ((it, r["data"]["decode"]) for r in responses for it in r["data"]["items"]):
    if dec["minPostingId"] + item[0] in seen_ids:
        continue
    seen_ids.add(dec["minPostingId"] + item[0])
    loc_desc = dec["locationDescriptions"]
    tags = {e[0]: e[1:] for e in item if isinstance(e, list)}
    strings = [e for e in item if isinstance(e, str)]
    loc = strings[0] if strings and "~" in strings[0] else None
    title = strings[-1] if strings else None
    lat = lon = None
    nb = None
    if loc:
        head, la, lo = loc.split("~")[:3]
        lat, lon = float(la), float(lo)
        idx = int(head.split(":")[1]) if ":" in head else 0
        nb = loc_desc[idx] if 0 < idx < len(loc_desc) and loc_desc[idx] else None
    rec = {
        "postingId": dec["minPostingId"] + item[0],
        "postedEpoch": dec["minPostedDate"] + item[1],
        "price": item[3] if isinstance(item[3], (int, float)) and item[3] >= 0 else None,
        "priceText": tags.get(10, [None])[0],
        "lat": lat, "lon": lon, "location": nb,
        "beds": tags[5][0] if 5 in tags else None,
        "sqft": tags[5][1] if 5 in tags and len(tags[5]) > 1 and tags[5][1] else None,
        "slug": tags[6][0], "viewId": tags[13][0],
        "images": [img_url(c) for c in tags.get(4, [])],
        "title": title,
        "rawItem": item,
    }
    p = os.path.join(det_dir, f"{rec['postingId']}.html")
    if os.path.exists(p):
        rec["detail"] = parse_detail(open(p, encoding="utf-8", errors="replace").read())
    records.append(rec)

os.makedirs(os.path.dirname(raw_out), exist_ok=True)
json.dump({"fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "method": "sapi.craigslist.org/web/v8/postings/search/full (split into price bands) + /view/d/ detail pages",
           "searchResponses": responses, "records": records}, open(raw_out, "w"), indent=1)

# ---- normalize ----
HOUSING = {"apartment": "apartment", "flat": "apartment", "loft": "apartment", "in-law": "apartment",
           "house": "house", "cottage/cabin": "house", "condo": "condo", "townhouse": "townhouse",
           "duplex": "other", "manufactured": "other", "assisted living": "other", "land": "other"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SCAM_PATTERNS = [
    (r"western union|moneygram|wire (the |a )?(money|deposit|transfer)|wire transfer", "wire transfer requested"),
    (r"\bzelle\b|cash ?app|\bvenmo\b", "wire/Zelle/gift card"),
    (r"gift ?cards?", "wire/Zelle/gift card"),
    (r"out of (the )?(country|state|town)|overseas|missionary|deployed|military (assignment|duty)", "owner out of the country"),
    (r"(send|pay|transfer)[^.]{0,40}deposit[^.]{0,40}(before|prior to)[^.]{0,30}(view|show|see|tour)", "asks for deposit before showing"),
    (r"(mail|ship|send)[^.]{0,20}(you )?the keys", "keys by mail"),
    (r"can(no|')t show|unable to show|drive by (only|the property)", "cannot show unit"),
]


def move_in(attrs):
    for a in attrs:
        t = a["text"].lower()
        if t == "available now":
            return "now"
        m = re.match(r"available (\w{3})\w* (\d{1,2})", t)
        if m and m.group(1) in MONTHS:
            mo, dy = MONTHS[m.group(1)], int(m.group(2))
            yr = 2026 if mo >= 11 else 2027  # data pulled Nov 2026
            try:
                return date(yr, mo, dy).isoformat()
            except ValueError:
                return t
    return None


listings = []
for r in records:
    det = r.get("detail") or {}
    if det.get("removed"):
        continue
    ld = det.get("ld") or {}
    attrs = det.get("attrs", [])
    atexts = [a["text"].lower() for a in attrs]
    beds = r["beds"]
    baths = None
    sqft = r["sqft"]
    for t in atexts:
        m = re.match(r"(\d+(?:\.\d+)?)br\s*/\s*(\d+(?:\.\d+)?|shared|split)ba", t.replace(" ", ""))
        if m:
            beds = float(m.group(1)) if beds is None else beds
            try:
                baths = float(m.group(2))
            except ValueError:
                pass
        m = re.match(r"(\d+)ft", t.replace(" ", ""))
        if m and not sqft:
            sqft = int(m.group(1))
    if baths is None and ld.get("numberOfBathroomsTotal") is not None and det:
        baths = float(ld["numberOfBathroomsTotal"])
    if isinstance(beds, float) and beds.is_integer():
        beds = int(beds)
    if isinstance(baths, float) and baths.is_integer():
        baths = int(baths)

    housing = next((HOUSING[t] for t in atexts if t in HOUSING), None)
    title_l = (r["title"] or "").lower()
    if housing is None:
        if re.search(r"\broom\b(?! ?mate)|room for rent", title_l) and not re.search(r"\d ?(br|bed)", title_l):
            housing = "room"
        elif re.search(r"\btownhome|townhouse", title_l):
            housing = "townhouse"
        elif re.search(r"\bcondo\b", title_l):
            housing = "condo"
        elif re.search(r"\bhouse\b|\bhome for rent", title_l):
            housing = "house"
        else:
            housing = "apartment"
    unit = "studio" if beds == 0 and housing in ("apartment", "other") else housing

    pets_bits = [a["text"] for a in attrs if "pets_cat" in a["class"] or re.search(r"(cats|dogs) are ok|no pets", a["text"].lower())]
    pets = "; ".join(dict.fromkeys(pets_bits)) or (("pets allowed" if ld.get("petsAllowed") else None) if det else None)

    price = r["price"]
    period = next((t.split(":", 1)[1].strip() for t in atexts if t.startswith("rent period:")), None)
    # extended-stay hotel ads: search price is the weekly rate; detail pages say "rent period: weekly"
    if period is None and not det and price is not None and price < 700 and re.search(r"\bweekly\b|week long", title_l):
        period = "weekly"
    if period in ("weekly", "daily"):
        unit = "other"
    # Some landlords pick the wrong rent period for a monthly price; only convert plausible rates.
    if price is not None and period == "weekly" and price < 1000:
        price = round(price * 52 / 12)
    elif price is not None and period == "daily" and price < 300:
        price = round(price * 30)

    addr = None
    la = ld.get("address") or {}
    if la.get("streetAddress"):
        addr = ", ".join(x for x in [la.get("streetAddress"), la.get("addressLocality"), " ".join(x for x in [la.get("addressRegion"), la.get("postalCode")] if x)] if x)
    elif det.get("mapaddress"):
        addr = det["mapaddress"]

    lat, lon = (det["map"]["lat"], det["map"]["lon"]) if det.get("map") else (r["lat"], r["lon"])
    if lat is not None and abs(lat) < 0.01 and abs(lon) < 0.01:
        lat = lon = None

    posted = det.get("times", {}).get("posted")
    posted_iso = (datetime.strptime(posted, "%Y-%m-%dT%H:%M:%S%z").isoformat() if posted
                  else datetime.fromtimestamp(r["postedEpoch"], timezone.utc).isoformat().replace("+00:00", "Z"))

    desc = det.get("body")
    photos = (det.get("thumbs") or r["images"])[:6]

    listings.append({
        "source": "craigslist",
        "sourceId": str(r["postingId"]),
        "url": f"https://www.craigslist.org/view/d/{r['slug']}/{r['viewId']}",
        "postedAt": posted_iso,
        "title": r["title"],
        "price": price,
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "unitType": unit,
        "neighborhood": r["location"],
        "address": addr,
        "lat": lat, "lon": lon,
        "moveIn": move_in(attrs),
        "pets": pets,
        "photos": photos,
        "description": desc[:1500] if desc else None,
        "scamFlags": [],
        "_rentPeriod": period,
        "_hasDetail": bool(det),
    })

# scam heuristics: price vs median for same bed count, plus text patterns
by_beds = {}
for l in listings:
    if l["price"] and l["beds"] is not None:
        by_beds.setdefault(min(l["beds"], 4), []).append(l["price"])
med = {b: statistics.median(v) for b, v in by_beds.items() if len(v) >= 5}
for l in listings:
    flags = []
    p, b = l["price"], l["beds"]
    if p is not None and p < 300:
        flags.append("price implausibly low")
    elif p is not None and b is not None and min(b, 4) in med and p < 0.6 * med[min(b, 4)]:
        flags.append("price far below market")
    text = f"{l['title'] or ''}\n{l['description'] or ''}".lower()
    for pat, label in SCAM_PATTERNS:
        if re.search(pat, text) and label not in flags:
            flags.append(label)
    l["scamFlags"] = flags

extra = {"_rentPeriod", "_hasDetail"}
clean = [{k: v for k, v in l.items() if k not in extra} for l in listings]
os.makedirs(os.path.dirname(out_path), exist_ok=True)
json.dump(clean, open(out_path, "w"), indent=1, ensure_ascii=False)

# summary
prices = sorted(l["price"] for l in clean if l["price"])
print("listings", len(clean), "with detail", sum(l["_hasDetail"] for l in listings))
print("price min/median/max", prices[0], statistics.median(prices), prices[-1], "n", len(prices))
print("medians by beds", med)
print("latlon", sum(l["lat"] is not None for l in clean), "photos", sum(bool(l["photos"]) for l in clean),
      "address", sum(bool(l["address"]) for l in clean), "baths", sum(l["baths"] is not None for l in clean),
      "desc", sum(bool(l["description"]) for l in clean))
print("unitTypes", {u: sum(l["unitType"] == u for l in clean) for u in set(l["unitType"] for l in clean)})
print("periods", {p: sum(l["_rentPeriod"] == p for l in listings) for p in set(l["_rentPeriod"] for l in listings)})
print("removed", sum(1 for r in records if (r.get("detail") or {}).get("removed")))
for l in clean:
    if l["scamFlags"]:
        print("FLAG", l["sourceId"], l["price"], l["beds"], l["title"][:60], l["scamFlags"])
