"""Minimal Apify client: run an actor, wait for it, return its dataset items.

Needs APIFY_TOKEN in the environment or in .env at the project root.
"""
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.apify.com/v2"

# python.org builds on macOS ship without CA certs; fall back to certifi's bundle.
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()


def token():
    if os.environ.get("APIFY_TOKEN"):
        return os.environ["APIFY_TOKEN"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("APIFY_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("APIFY_TOKEN not set (env var or .env)")


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
        return json.load(r)


def run_actor(actor, run_input):
    run = call("POST", f"/acts/{actor}/runs", run_input)["data"]
    print(f"Started {actor} run {run['id']}")
    while run["status"] in ("READY", "RUNNING"):
        time.sleep(15)
        run = call("GET", f"/actor-runs/{run['id']}")["data"]
        print("  status:", run["status"])
    if run["status"] != "SUCCEEDED":
        sys.exit(f"Run ended with status {run['status']}")
    return call("GET", f"/datasets/{run['defaultDatasetId']}/items?clean=true&format=json")


def save(items, name):
    out = ROOT / "data/raw" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, indent=1, ensure_ascii=False))
    print(f"Saved {len(items)} items to {out.relative_to(ROOT)}")
