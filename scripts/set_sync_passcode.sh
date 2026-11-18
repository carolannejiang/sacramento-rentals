#!/bin/bash
# Set the passcode that unlocks synced Saved/Hidden/Contacted marks on the site.
# Prompts twice (hidden), stores it as SYNC_KEY on the Vercel project, then republishes.
cd "$(dirname "$0")/.." || exit 1
read -r -s -p "New passcode (8+ characters): " p1; echo
read -r -s -p "Type it again: " p2; echo
[ "$p1" != "$p2" ] && { echo "They don't match. Nothing changed."; exit 1; }
[ ${#p1} -lt 8 ] && { echo "Use at least 8 characters. Nothing changed."; exit 1; }
cd site || exit 1
vercel env rm SYNC_KEY production -y >/dev/null 2>&1
printf %s "$p1" | vercel env add SYNC_KEY production >/dev/null 2>&1 || { echo "Couldn't save it to Vercel."; exit 1; }
cd .. || exit 1
grep -v '^SYNC_KEY=' .env > .env.tmp 2>/dev/null; printf 'SYNC_KEY=%s\n' "$p1" >> .env.tmp; mv .env.tmp .env; chmod 600 .env
rm -f sync-link.txt
gh workflow run update.yml -R carolannejiang/sacramento-rentals >/dev/null && echo "Saved. The site is republishing; the new passcode works in about 3 minutes. You can close this tab."
