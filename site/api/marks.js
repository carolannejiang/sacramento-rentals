// Saved / hidden / contacted marks per person, shared between everyone who has an account.
//
// An account is a name + passcode. Signing in with a new name creates it. Each person's saved
// and contacted listings are visible to every signed-in person; hidden listings stay private.
// Storage is a private Vercel Blob store where the data lives in the pathnames:
//   users/<slug>/<name, base64url>.<salt>.<scrypt hash>
//   marks/<slug>/<set>/<listing id, base64url>     (empty blob; delete = unmark)
// so two devices never overwrite each other. Requests carry x-user and x-pass headers
// (URI-encoded).
import { del, list, put } from "@vercel/blob";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const SETS = ["fav", "hidden", "messaged"];
const PRIVATE_SETS = ["hidden"];
const ORIGINS = ["https://sacramento-rentals.vercel.app", "https://carolannejiang.github.io"];

const b64 = (s) => Buffer.from(s).toString("base64url");
const unb64 = (s) => Buffer.from(s, "base64url").toString();
const slugOf = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30);
const hash = (passcode, salt) => scryptSync(passcode, salt, 32).toString("hex");

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
  if (!path) return null;
  const [encName, salt, digest] = path.split("/")[2].split(".");
  return { name: unb64(encName), salt, digest };
}

function passcodeMatches(user, passcode) {
  const given = Buffer.from(hash(passcode, user.salt), "hex");
  return timingSafeEqual(given, Buffer.from(user.digest, "hex"));
}

// Returns the signed-in person, or null.
async function authenticate(request) {
  const { slug, passcode } = credentials(request);
  if (!slug || !passcode) return null;
  const user = await findUser(slug);
  return user && passcodeMatches(user, passcode) ? { ...user, slug } : null;
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
    if (!marks[slug]?.[set] || (PRIVATE_SETS.includes(set) && slug !== me.slug)) continue;
    marks[slug][set].push(unb64(id));
  }
  return json(request, { me: { slug: me.slug, name: me.name }, people, marks });
}

export async function POST(request) {
  const body = await request.json().catch(() => ({}));

  if (body.action === "login") {
    const { name, slug, passcode } = credentials(request);
    if (!slug) return json(request, { error: "Enter a name" }, 400);
    if (passcode.length < 6) return json(request, { error: "Use a passcode of at least 6 characters" }, 400);
    const user = await findUser(slug);
    if (user) return passcodeMatches(user, passcode) ? json(request, { name: user.name, slug }) : denied(request);
    const salt = randomBytes(16).toString("hex");
    await put(`users/${slug}/${b64(name)}.${salt}.${hash(passcode, salt)}`, "1", { access: "private", addRandomSuffix: false });
    return json(request, { name, slug, created: true });
  }

  const me = await authenticate(request);
  if (!me) return denied(request);
  const { set, id, on } = body;
  if (!SETS.includes(set) || typeof id !== "string" || id.length > 200) return json(request, { error: "bad request" }, 400);
  const pathname = `marks/${me.slug}/${set}/${b64(id)}`;
  if (on) await put(pathname, "1", { access: "private", allowOverwrite: true, addRandomSuffix: false });
  else await del(pathname).catch(() => {});
  return json(request, { ok: true });
}
