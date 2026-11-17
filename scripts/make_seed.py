"""Write seed/ — a privacy-safe starting copy of data/ that can be committed to a public repo.

The scheduled workflow keeps its working data in the GitHub Actions cache; when that cache
is empty (first run, or evicted) it starts from seed/ instead of re-pulling and re-sorting
30 days of Facebook posts. Poster names/ids and post text are left out.
Usage: python3 scripts/make_seed.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"


def main():
    if SEED.exists():
        shutil.rmtree(SEED)
    (SEED / "data/listings").mkdir(parents=True)
    (SEED / "data/raw").mkdir(parents=True)
    (SEED / "data/work").mkdir(parents=True)

    for f in (ROOT / "data/listings").glob("*.json"):
        rows = [{k: v for k, v in x.items() if k not in ("poster", "posterId")} for x in json.loads(f.read_text())]
        (SEED / "data/listings" / f.name).write_text(json.dumps(rows, ensure_ascii=False))

    # Only what later runs need from old posts: ids, post time (30-day pruning) and photos.
    raw = json.loads((ROOT / "data/raw/facebook.json").read_text())
    slim = [{"id": i.get("id"), "legacyId": i.get("legacyId"), "time": i.get("time"),
             "attachments": [{"thumbnail": a["thumbnail"]} for a in i.get("attachments") or [] if a.get("thumbnail")][:6]}
            for i in raw]
    (SEED / "data/raw/facebook.json").write_text(json.dumps(slim))

    for rel in ("data/state.json", "data/work/facebook_processed.json", "data/work/zillow_pulled_at"):
        if (ROOT / rel).exists():
            shutil.copy(ROOT / rel, SEED / rel)
    print("seed written:", sum(f.stat().st_size for f in SEED.rglob("*") if f.is_file()) // 1024, "KB")


if __name__ == "__main__":
    main()
