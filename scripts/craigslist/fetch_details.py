"""Fetch Craigslist detail pages for up to N search results not already cached (polite: ~1 req/sec).
Usage: python3 -I fetch_details.py <search_dir> <out_dir> <N>
"""
import glob, json, os, subprocess, sys, time

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

search_dir, out_dir, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.makedirs(out_dir, exist_ok=True)
items = []
for f in sorted(glob.glob(os.path.join(search_dir, "*.json"))):
    d = json.load(open(f))["data"]
    items += [(d["decode"]["minPostingId"] + it[0], it) for it in d["items"]]

fetched = 0
for pid, item in items:
    if fetched >= n:
        break
    tags = {e[0]: e for e in item if isinstance(e, list)}
    url = f"https://www.craigslist.org/view/d/{tags[6][1]}/{tags[13][1]}"
    path = os.path.join(out_dir, f"{pid}.html")
    if os.path.exists(path):
        continue
    r = subprocess.run(["curl", "-s", "-A", UA, "-H", "Accept-Language: en-US,en;q=0.9",
                        "-o", path, "-w", "%{http_code}", url], capture_output=True, text=True)
    status = r.stdout.strip()
    body = open(path).read() if os.path.exists(path) else ""
    if status != "200" and os.path.exists(path):
        os.rename(path, path + f".{status}")
    fetched += 1
    print(pid, status, len(body), flush=True)
    if status in ("403", "429"):
        print("blocked; stopping", flush=True)
        break
    time.sleep(1.1)
print("fetched", fetched)
