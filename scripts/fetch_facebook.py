"""Pull recent posts from the Facebook groups in sources/facebook_groups.json via Apify.

New posts are added to data/raw/facebook.json; posts older than KEEP_DAYS are dropped.
Usage: python3 scripts/fetch_facebook.py [window] [posts_per_group] [group_url]
  window: how far back to pull, e.g. "8 hours" or "30 days" (default "30 days")
  group_url: pull only this group
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from apify import ROOT, run_actor, save

KEEP_DAYS = 30


def main():
    window = sys.argv[1] if len(sys.argv) > 1 else "30 days"
    per_group = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    only = sys.argv[3] if len(sys.argv) > 3 else None
    urls = [only] if only else [g["url"] for g in json.loads((ROOT / "sources/facebook_groups.json").read_text())]
    items = run_actor("apify~facebook-groups-scraper", {
        "startUrls": [{"url": u} for u in urls],
        "resultsLimit": per_group,
        "viewOption": "CHRONOLOGICAL",
        "onlyPostsNewerThan": window,
    })
    raw = ROOT / "data/raw/facebook.json"
    existing = json.loads(raw.read_text()) if raw.exists() else []
    ids = {i.get("id") for i in items}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    merged = [i for i in existing if i.get("id") not in ids] + items
    merged = [i for i in merged if (i.get("time") or "") >= cutoff[:19]]
    print(f"{len(items)} posts pulled, {len(merged)} kept within {KEEP_DAYS} days")
    save(merged, "facebook.json")


if __name__ == "__main__":
    main()
