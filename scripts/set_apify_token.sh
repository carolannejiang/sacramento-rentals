#!/bin/bash
# Prompts for your Apify API token (hidden) and saves it to .env for scripts/fetch_facebook.py.
cd "$(dirname "$0")/.." || exit 1
read -r -s -p "Paste your Apify API token and press Enter: " t
echo
[ -z "$t" ] && { echo "No token entered."; exit 1; }
printf 'APIFY_TOKEN=%s\n' "$t" > .env
chmod 600 .env
echo "Saved. You can close this tab."
