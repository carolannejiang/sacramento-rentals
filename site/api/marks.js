// Saved / hidden / contacted / tour marks per person, shared between everyone in the group.
//
// Everyone signs in with their name plus the group passcode (GROUP_PASSCODE env var). Names
// ignore case, spaces and punctuation, so "Carol Anne" and "carolanne" are the same account.
// The group shares one list per mark: everyone sees every mark with who made it, and unmarking
// a listing clears it for everyone (hidden included). Storage is a private Vercel Blob store
// where the data lives in the pathnames:
//   users/<slug>/<display name, base64url>
//   marks/<slug>/<set>/<listing id, base64url>     (empty blob; delete = unmark)
// so two devices never overwrite each other. Requests carry x-user and x-pass headers
// (URI-encoded).
import { del, list, put } from "@vercel/blob";
import { timingSafeEqual } from "node:crypto";

const SETS = ["fav", "hidden", "messaged", "tourScheduled", "toured"];
const ORIGINS = ["https://sacramento-rentals.vercel.app", "https://carolannejiang.github.io"];

const b64 = (s) => Buffer.from(s).toString("base64url");
const unb64 = (s) => Buffer.from(s, "base64url").toString();
const slugOf = (name) => name.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);

function headers(request) {
  const origin = request.headers.get("origin");
  return {
    "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
    "Access-Control-Allow-Headers": "content-type, x-user, x-pass",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Cache-Control": "no-store",
    Vary: "Origin",
  };
}

const json = (request, body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...headers(request), "Content-Type": "application/json" } });

// A wrong passcode waits before answering, so guessing one takes a long time.
const denied = async (request, error = "wrong passcode") => {
  await new Promise((r) => setTimeout(r, 1500));
  return json(request, { error }, 401);
};

function credentials(request) {
  const read = (h) => { try { return decodeURIComponent(request.headers.get(h) || ""); } catch { return ""; } };
  const name = read("x-user").trim().slice(0, 30);
  return { name, slug: slugOf(name), passcode: read("x-pass") };
}

async function listAll(prefix) {
  const out = [];
  let cursor;
  do {
    const page = await list({ prefix, cursor, limit: 1000 });
    out.push(...page.blobs.map((b) => b.pathname));
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);
  return out;
}

async function findUser(slug) {
  const [path] = await listAll(`users/${slug}/`);
  return path ? { slug, name: unb64(path.split("/")[2]) } : null;
}

function passcodeMatches(passcode) {
  const given = Buffer.from(passcode.trim().toLowerCase());
  const expected = Buffer.from((process.env.GROUP_PASSCODE || "").trim().toLowerCase());
  return expected.length > 0 && given.length === expected.length && timingSafeEqual(given, expected);
}

// Returns the signed-in person, or null.
async function authenticate(request) {
  const { slug, passcode } = credentials(request);
  if (!slug || !passcodeMatches(passcode)) return null;
  return findUser(slug);
}

export function OPTIONS(request) {
  return new Response(null, { status: 204, headers: headers(request) });
}

export async function GET(request) {
  const me = await authenticate(request);
  if (!me) return denied(request);
  const people = (await listAll("users/")).map((p) => {
    const [, slug, file] = p.split("/");
    return { slug, name: unb64(file.split(".")[0]) };
  });
  const marks = Object.fromEntries(people.map((p) => [p.slug, Object.fromEntries(SETS.map((s) => [s, []]))]));
  for (const p of await listAll("marks/")) {
    const [, slug, set, id] = p.split("/");
    if (!marks[slug]?.[set]) continue;
    marks[slug][set].push(unb64(id));
  }
  return json(request, { me: { slug: me.slug, name: me.name }, people, marks });
}

export async function POST(request) {
  const body = await request.json().catch(() => ({}));

  if (body.action === "login") {
    const { name, slug, passcode } = credentials(request);
    if (!slug) return json(request, { error: "Enter your name" }, 400);
    if (!passcodeMatches(passcode)) return denied(request);
    const user = await findUser(slug);
    if (user) return json(request, user);
    // Only create an account when the person confirmed it, so a typo doesn't make a new one.
    if (!body.create) return json(request, { error: "no account", slug }, 404);
    await put(`users/${slug}/${b64(name)}`, "1", { access: "private", addRandomSuffix: false });
    return json(request, { name, slug, created: true });
  }

  const me = await authenticate(request);
  if (!me) return denied(request);
  const { set, id, on } = body;
  if (!SETS.includes(set) || typeof id !== "string" || id.length > 200) return json(request, { error: "bad request" }, 400);
  const pathOf = (slug) => `marks/${slug}/${set}/${b64(id)}`;
  if (on) await put(pathOf(me.slug), "1", { access: "private", allowOverwrite: true, addRandomSuffix: false });
  else {
    // Unmarking clears the listing from the shared list: everyone's mark on it goes.
    const slugs = (await listAll("users/")).map((p) => p.split("/")[1]);
    await del(slugs.map(pathOf)).catch(() => {});
  }
  return json(request, { ok: true });
}
