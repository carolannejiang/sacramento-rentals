"""Fetch every Craigslist search result by splitting the search into price bands.

The search API returns at most 360 items per query and has no working paging, so each
band must stay under 360. Prints a warning if one doesn't.
Usage: python3 -I fetch_search.py <out_dir>
"""
import json, os, subprocess, sys, time

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = ("https://sapi.craigslist.org/web/v8/postings/search/full?batch=12-0-360-0-0&cc=US&lang=en"
        "&searchPath=apa&lat=38.5726&lon=-121.4747&search_distance=3.3")
BANDS = [(None, 1400), (1401, 1800), (1801, 2300), (2301, None)]

out_dir = sys.argv[1]
os.makedirs(out_dir, exist_ok=True)
total = None
for lo, hi in BANDS:
    q = (f"&min_price={lo}" if lo else "") + (f"&max_price={hi}" if hi else "")
    resp = json.loads(subprocess.run(["curl", "-s", "-A", UA, BASE + q], capture_output=True, text=True).stdout)
    d = resp["data"]
    if len(d["items"]) < d["totalResultCount"]:
        print(f"WARNING: band {lo}-{hi} has {d['totalResultCount']} results, only got {len(d['items'])}; split it")
    json.dump(resp, open(os.path.join(out_dir, f"price_{lo or 0}-{hi or 'max'}.json"), "w"))
    print(f"band {lo}-{hi}: {len(d['items'])} items")
    time.sleep(1.2)
