// Shared saved / hidden / contacted marks, so they follow you across devices.
// Each mark is one empty blob at marks/<set>/<listing id, base64url> in a private Vercel Blob
// store: adding is a put, removing is a delete, so two devices never overwrite each other.
// Requests must carry the x-sync-key header (URI-encoded) matching the SYNC_KEY passcode.
import { del, list, put } from "@vercel/blob";
import { timingSafeEqual } from "node:crypto";

const SETS = ["fav", "hidden", "messaged"];
const ORIGINS = ["https://sacramento-rentals.vercel.app", "https://carolannejiang.github.io"];

const b64 = (s) => Buffer.from(s).toString("base64url");
const unb64 = (s) => Buffer.from(s, "base64url").toString();

function headers(request) {
  const origin = request.headers.get("origin");
  return {
    "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
    "Access-Control-Allow-Headers": "content-type, x-sync-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Cache-Control": "no-store",
    Vary: "Origin",
  };
}

function authorized(request) {
  let raw = request.headers.get("x-sync-key") || "";
  try { raw = decodeURIComponent(raw); } catch {}
  const given = Buffer.from(raw);
  const expected = Buffer.from(process.env.SYNC_KEY || "");
  return expected.length > 0 && given.length === expected.length && timingSafeEqual(given, expected);
}

// A wrong passcode waits before answering, so guessing a short passcode takes a long time.
const denied = async (request) => {
  await new Promise((r) => setTimeout(r, 1500));
  return json(request, { error: "bad passcode" }, 401);
};

const json = (request, body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...headers(request), "Content-Type": "application/json" } });

export function OPTIONS(request) {
  return new Response(null, { status: 204, headers: headers(request) });
}

export async function GET(request) {
  if (!authorized(request)) return denied(request);
  const marks = Object.fromEntries(SETS.map((s) => [s, []]));
  let cursor;
  do {
    const page = await list({ prefix: "marks/", cursor, limit: 1000 });
    for (const blob of page.blobs) {
      const [, set, id] = blob.pathname.split("/");
      if (marks[set]) marks[set].push(unb64(id));
    }
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);
  return json(request, marks);
}

export async function POST(request) {
  if (!authorized(request)) return denied(request);
  const { set, id, on } = await request.json().catch(() => ({}));
  if (!SETS.includes(set) || typeof id !== "string" || id.length > 200) return json(request, { error: "bad request" }, 400);
  const pathname = `marks/${set}/${b64(id)}`;
  if (on) await put(pathname, "1", { access: "private", allowOverwrite: true, addRandomSuffix: false });
  else await del(pathname).catch(() => {});
  return json(request, { ok: true });
}
