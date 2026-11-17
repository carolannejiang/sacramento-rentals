"""Split not-yet-processed posts in data/raw/facebook.json into compact chunks for agents to parse.

Posts whose ids appear in data/work/facebook_processed.json are skipped.
Usage: python3 scripts/prepare_facebook_chunks.py <prefix> [chunk_size]
Writes data/work/<prefix>_chunk<N>.json and prints the chunk paths.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def compact(i):
    atts = i.get("attachments") or []
    sp = i.get("sharedPost") if isinstance(i.get("sharedPost"), dict) else {}
    user = i.get("user") or {}
    return {
        "sourceId": i.get("legacyId") or i.get("id"), "url": i.get("url"), "postedAt": i.get("time"),
        "group": i.get("groupTitle"), "poster": user.get("name"), "posterId": user.get("id"),
        "text": (i.get("text") or "")[:2500],
        "mpTitle": i.get("title"), "mpPrice": i.get("price"), "mpLocation": i.get("location"),
        "sharedText": (sp.get("text") or "")[:1500] or None,
        "photoCount": sum(1 for a in atts if a.get("thumbnail")),
        "imageText": [a["ocrText"][:300] for a in atts if a.get("ocrText")][:3],
    }


def main():
    prefix = sys.argv[1]
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    done_path = ROOT / "data/work/facebook_processed.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    posts = [compact(i) for i in json.loads((ROOT / "data/raw/facebook.json").read_text())]
    todo = [p for p in posts if p["sourceId"] not in done]
    print(f"{len(posts)} posts, {len(todo)} not yet processed")
    for n in range(0, len(todo), size):
        out = ROOT / f"data/work/{prefix}_chunk{n // size + 1}.json"
        out.write_text(json.dumps(todo[n:n + size], ensure_ascii=False, indent=1))
        print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
