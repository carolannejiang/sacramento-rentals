"""Sort not-yet-processed Facebook posts into whole-unit listings with the Claude API.

Reads data/raw/facebook.json, skips ids in data/work/facebook_processed.json, sends the rest
to Claude in batches, appends offerings to data/listings/facebook_auto.json.
Needs ANTHROPIC_API_KEY (or another credential the anthropic SDK picks up).
Usage: python scripts/parse_facebook.py [batch_size]
"""
import json
import sys
from pathlib import Path
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel

from prepare_facebook_chunks import compact

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data/work/facebook_processed.json"
OUT = ROOT / "data/listings/facebook_auto.json"
RULES = (ROOT / "scripts/facebook_parse_prompt.md").read_text().split("## Agent output")[0]
SYSTEM = RULES + "\nYou get a JSON array of posts. Return one result per input post, in any order, keyed by sourceId. Fill `listing` only when kind is \"offering\"."


class Listing(BaseModel):
    title: str
    price: Optional[float]
    deposit: Optional[float]
    beds: Optional[float]
    baths: Optional[float]
    sqft: Optional[float]
    unitType: Literal["apartment", "house", "condo", "townhouse", "studio", "duplex", "other"]
    neighborhood: Optional[str]
    address: Optional[str]
    moveIn: Optional[str]
    leaseTerm: Optional[str]
    pets: Optional[str]
    utilitiesIncluded: Optional[bool]
    contact: Optional[str]
    description: Optional[str]
    scamFlags: List[str]


class PostResult(BaseModel):
    sourceId: str
    kind: Literal["offering", "shared", "seeking", "other"]
    listing: Optional[Listing]


class BatchResult(BaseModel):
    results: List[PostResult]


def classify(client, posts):
    response = client.messages.parse(
        model="claude-opus-5-5",
        max_tokens=16000,
        output_config={"effort": "low"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(posts, ensure_ascii=False)}],
        output_format=BatchResult,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"batch not parsed (stop_reason={response.stop_reason})")
    return response.parsed_output.results


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    done = set(json.loads(PROCESSED.read_text())) if PROCESSED.exists() else set()
    posts = [compact(i) for i in json.loads((ROOT / "data/raw/facebook.json").read_text())]
    todo = [p for p in posts if p["sourceId"] not in done]
    listings = json.loads(OUT.read_text()) if OUT.exists() else []
    print(f"{len(todo)} new Facebook posts to sort")

    client = anthropic.Anthropic()
    counts = {}
    for n in range(0, len(todo), size):
        batch = {p["sourceId"]: p for p in todo[n:n + size]}
        try:
            results = classify(client, list(batch.values()))
        except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError) as e:
            print(f"  batch {n // size + 1} failed, will retry next run: {e}")
            continue
        for r in results:
            post = batch.get(r.sourceId)
            if post is None:
                continue
            counts[r.kind] = counts.get(r.kind, 0) + 1
            if r.kind == "offering" and r.listing:
                listings.append({
                    "source": "facebook", "sourceId": post["sourceId"], "url": post["url"],
                    "group": post["group"], "postedAt": post["postedAt"],
                    "poster": post["poster"], "posterId": post["posterId"],
                    **r.listing.model_dump(), "lat": None, "lon": None, "sharedSpace": False,
                })
            done.add(r.sourceId)
        # Save after every batch so a crash doesn't lose finished work.
        OUT.write_text(json.dumps(listings, indent=1, ensure_ascii=False))
        PROCESSED.parent.mkdir(parents=True, exist_ok=True)
        PROCESSED.write_text(json.dumps(sorted(done)))
    print("  sorted:", counts)


if __name__ == "__main__":
    main()
