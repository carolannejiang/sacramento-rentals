// Sacramento Rentals: renders site/listings.json with filters, a map, and saved/hidden lists.
// Saved/hidden state and filters live in this browser's localStorage only.

const $ = (id) => document.getElementById(id);
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};

const SOURCES = { zillow: "Zillow", craigslist: "Craigslist", facebook: "Facebook" };
const TYPE_LABELS = { apartment: "Apartment", studio: "Studio", house: "House", condo: "Condo", townhouse: "Townhouse", duplex: "Duplex", other: "Other" };
// Which unitType values each "Home type" filter option covers.
const TYPE_GROUPS = { apartment: ["apartment", "studio"], house: ["house"], condo: ["condo", "townhouse"], duplex: ["duplex"] };
const HIGHLIGHT_GROUPS = ["Laundry", "Cooling", "Parking", "In the unit", "Appliances", "Community"];
const FILTER_IDS = ["maxPrice", "minBeds", "homeType", "minSqft", "listedBy", "postedWithin", "dogs", "sort", "q", "newOnly", "noPrice", "hideHotels", "hideFlagged"];

let listings = [];
let destinations = [];
let byId = new Map();
let view = "all";
let fav = new Set(store.get("fav", []));
let hidden = new Set(store.get("hidden", []));
let messaged = new Set(store.get("messaged", []));
const lastVisit = store.get("lastVisit", null);
let map, markers;

function dogsOk(x) {
  if (x.source === "zillow") return true; // the Zillow search is filtered to small dogs OK
  const p = (x.pets || "").toLowerCase();
  if (!p) return null;
  if (/no (dogs|pets)|dogs? not allowed|pets? not allowed|cats only/.test(p)) return false;
  return /dog|pets? (ok|allowed|welcome|friendly|negotiable)|pet[- ]friendly/.test(p) ? true : null;
}

function isNew(x) { return lastVisit && x.firstSeen > lastVisit; }

// Best known post date. Some Zillow buildings have none; for those, "first seen" only means
// something for listings that appeared after the site's first import.
let importCutoff = "";
function postedDate(x) {
  if (x.postedAt) return x.postedAt;
  return x.firstSeen > importCutoff ? x.firstSeen : null;
}

function filtered() {
  const f = readFilters();
  const q = f.q.trim().toLowerCase();
  let out = listings.filter((x) => {
    if (view === "fav") return fav.has(x.id);
    if (view === "messaged") return messaged.has(x.id);
    if (view === "hidden") return hidden.has(x.id);
    if (hidden.has(x.id)) return false;
    if (!(x.sources || [x.source]).some((s) => f.sources.includes(s))) return false;
    if (x.price == null ? !f.noPrice : x.price > f.maxPrice) return false;
    if (f.minBeds > 0 && x.beds != null && x.beds < f.minBeds) return false;
    if (f.homeType !== "any" && !TYPE_GROUPS[f.homeType].includes(x.unitType)) return false;
    // Unknown posters are left out of both choices: only show what's actually known.
    if (f.listedBy !== "any" && x.listedBy !== f.listedBy) return false;
    if (f.minSqft && x.sqft && x.sqft < f.minSqft) return false;
    if (f.postedWithin && (!postedDate(x) || Date.now() - new Date(postedDate(x)) > f.postedWithin * 864e5)) return false;
    // Listings without a known location stay visible, like unknown sqft.
    for (const [id, max] of Object.entries(f.maxDrive)) if (max && x.commute?.[id]?.min > max) return false;
    const d = dogsOk(x);
    if (f.dogs === "yes" && d !== true) return false;
    if (f.dogs === "maybe" && d === false) return false;
    if (f.hideHotels && x.weeklyHotel) return false;
    if (f.hideFlagged && x.scamFlags?.length) return false;
    if (f.newOnly && !isNew(x)) return false;
    if (q && !`${x.title} ${x.neighborhood} ${x.address} ${x.description} ${Object.values(x.features || {}).flat().join(" ")}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const price = (x) => x.price ?? Infinity;
  if (f.sort.startsWith("drive_")) {
    const id = f.sort.slice(6);
    const t = (x) => x.commute?.[id]?.min ?? Infinity;
    out.sort((a, b) => t(a) - t(b));
  } else if (f.sort === "priceAsc") out.sort((a, b) => price(a) - price(b));
  else if (f.sort === "priceDesc") out.sort((a, b) => (b.price ?? -1) - (a.price ?? -1));
  else out.sort((a, b) => (postedDate(b) || "").localeCompare(postedDate(a) || ""));
  return out;
}

function readFilters() {
  return {
    maxPrice: Number($("maxPrice").value) || Infinity,
    minBeds: Number($("minBeds").value),
    homeType: $("homeType").value,
    listedBy: $("listedBy").value,
    minSqft: Number($("minSqft").value) || 0,
    postedWithin: Number($("postedWithin").value),
    maxDrive: Object.fromEntries(destinations.map((d) => [d.id, Number($(`drive_${d.id}`)?.value) || 0])),
    dogs: $("dogs").value,
    sort: $("sort").value,
    q: $("q").value,
    newOnly: $("newOnly").checked,
    noPrice: $("noPrice").checked,
    hideHotels: $("hideHotels").checked,
    hideFlagged: $("hideFlagged").checked,
    sources: [...document.querySelectorAll("#sources input:checked")].map((i) => i.value),
  };
}

function saveFilters() {
  const f = {};
  for (const id of FILTER_IDS) { const el = $(id); f[id] = el.type === "checkbox" ? el.checked : el.value; }
  f.sources = readFilters().sources;
  store.set("filters", f);
}

function restoreFilters() {
  const f = store.get("filters", null);
  if (!f) return;
  for (const id of FILTER_IDS) {
    const el = $(id);
    if (!(id in f) || !el) continue;
    if (el.type === "checkbox") el.checked = f[id]; else el.value = f[id];
  }
  document.querySelectorAll("#sources input").forEach((i) => { i.checked = !f.sources || f.sources.includes(i.value); });
}

function ago(iso) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso)) / 864e5);
  return days <= 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

function day(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} (${ago(iso)})`;
}

function money(n) { return n == null ? "Price not listed" : "$" + Math.round(n).toLocaleString() + "/mo"; }

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function card(x) {
  const specs = [
    x.unitType !== "studio" && x.unitType !== "other" && TYPE_LABELS[x.unitType],
    x.beds != null && (x.beds === 0 ? "Studio" : `${x.beds} bd`),
    x.baths != null && `${x.baths} ba`,
    x.sqft ? `${Math.round(x.sqft).toLocaleString()} sqft` : "sqft not listed",
  ].filter(Boolean).join(" · ");
  const where = [x.neighborhood, x.address].filter(Boolean).join(" — ");
  const drives = x.commute ? destinations.map((d) => {
    const c = x.commute[d.id];
    if (!c) return "";
    return "🚗 " + (c.straightLine ? `≈${c.mi} mi to ${esc(d.label)}` : `<b>${c.min} min</b> (${c.mi} mi) to ${esc(d.label)}`);
  }).filter(Boolean).join("<br>") : "";
  const badges = [
    isNew(x) && `<span class="badge new">New</span>`,
    messaged.has(x.id) && `<span class="badge messaged">✉ Contacted</span>`,
    ...(x.sources || [x.source]).map((s) => `<span class="badge src-${s}">${SOURCES[s] || s}${s === x.source && x.group ? " · " + esc(x.group.split(/[|,]/)[0].trim()) : ""}</span>`),
    x.listedBy === "individual" && `<span class="badge lister" title="${esc(x.listerName || "Posted by an owner or tenant")}">👤 Individual</span>`,
    x.listedBy === "company" && `<span class="badge lister">🏢 ${esc(x.listerName || "Property manager")}</span>`,
    dogsOk(x) === true && `<span class="badge">Dogs OK</span>`,
    x.moveIn && `<span class="badge">Move-in ${esc(x.moveIn)}</span>`,
    x.specialOffer && `<span class="badge offer" title="${esc(x.specialOffer)}">🎁 Special offer</span>`,
    x.alsoAt?.length && `<span class="badge">Posted ${x.alsoAt.length + 1}×</span>`,
    ...(x.scamFlags || []).map((f) => `<span class="badge warn">⚠ ${esc(f)}</span>`),
  ].filter(Boolean).join("");
  const n = x.photos?.length || 0;
  const photo = n
    ? `<div class="gallery" data-i="0">
        <span class="nophoto-text">Photo unavailable</span>
        <img class="photo" loading="lazy" src="${esc(x.photos[0])}" alt="" data-act="zoom" onerror="this.classList.add('broken')">
        ${n > 1 ? `<button class="nav prev" data-act="prev" aria-label="Previous photo">‹</button>
          <button class="nav next" data-act="next" aria-label="Next photo">›</button>
          <span class="pcount">1/${n}</span>` : ""}
      </div>`
    : `<div class="photo nophoto">No photo</div>`;
  // A few key features up front; every feature, grouped, when the card is expanded.
  const feats = x.features || {};
  // Short items like "In unit" or "On street" need their group to make sense on their own.
  const label = (g, t) => (g === "Laundry" && !/laundry|washer|w\/d/i.test(t)) || (g === "Parking" && !/park|garage|carport/i.test(t))
    ? `${g}: ${t.toLowerCase()}` : t;
  const highlights = HIGHLIGHT_GROUPS.flatMap((g) => (feats[g] || []).map((t) => label(g, t))).slice(0, 6);
  const featureList = Object.entries(feats).map(([g, list]) =>
    `<div><dt>${esc(g)}</dt><dd>${list.map(esc).join(" · ")}</dd></div>`).join("");
  const hasMore = x.description || featureList || x.specialOffer;
  const copies = (x.alsoAt || []).map((c, i) =>
    `<a href="${esc(c.url)}" target="_blank" rel="noopener">${c.source && c.source !== x.source ? SOURCES[c.source] + " ↗" : `copy ${i + 2}`}</a>`).join(" ");
  return `<li class="card" id="c-${CSS.escape(x.id)}" data-id="${esc(x.id)}">
    <div class="corner">
      <button data-act="fav" class="star ${fav.has(x.id) ? "on" : ""}" aria-pressed="${fav.has(x.id)}" aria-label="Save" title="${fav.has(x.id) ? "Saved" : "Save"}">${fav.has(x.id) ? "★" : "☆"}</button>
      <button data-act="messaged" class="${messaged.has(x.id) ? "on" : ""}" aria-pressed="${messaged.has(x.id)}">${messaged.has(x.id) ? "✓ Contacted" : "✉ Contacted"}</button>
    </div>
    ${photo}
    <div>
      <div class="top"><span class="price">${money(x.price)}</span><span class="specs">${specs}</span><span class="specs" title="${x.postedAt ? "Date the listing was posted" : "The source doesn't give a post date"}">${
        x.postedAt ? "posted " + day(x.postedAt) : postedDate(x) ? "first seen " + day(x.firstSeen) : "post date not listed"}</span></div>
      <p class="title">${esc(x.title)}</p>
      ${where ? `<p class="where">${esc(where)}</p>` : ""}
      <p class="drive">${drives || "🚗 Location not listed"}</p>
      <div class="badges">${badges}</div>
      ${highlights.length ? `<div class="highlights">${highlights.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
      ${x.description ? `<p class="desc">${esc(x.description)}</p>` : ""}
      <div class="details">
        ${x.specialOffer ? `<p class="offer">🎁 ${esc(x.specialOffer)}</p>` : ""}
        ${featureList ? `<dl class="features">${featureList}</dl>` : ""}
      </div>
      <div class="actions">
        <a href="${esc(x.url)}" target="_blank" rel="noopener">${x.sources?.length > 1 ? SOURCES[x.source] : "Open listing"} ↗</a> ${copies}
        <button data-act="hide">${hidden.has(x.id) ? "Unhide" : "Hide"}</button>
        ${hasMore ? `<button data-act="more">Details</button>` : ""}
      </div>
    </div>
  </li>`;
}

function render() {
  const rows = filtered();
  $("count").textContent = `${rows.length} listing${rows.length === 1 ? "" : "s"}`;
  $("list").innerHTML = rows.slice(0, 400).map(card).join("") + (rows.length > 400 ? `<li class="count">Showing first 400 — narrow the filters to see more.</li>` : "");
  $("favCount").textContent = fav.size ? `(${fav.size})` : "";
  $("hiddenCount").textContent = hidden.size ? `(${hidden.size})` : "";
  $("messagedCount").textContent = messaged.size ? `(${messaged.size})` : "";
  markers.clearLayers();
  for (const x of rows) {
    if (x.lat == null || x.lon == null) continue;
    L.circleMarker([x.lat, x.lon], { radius: 6, weight: 1, color: "#fff", fillColor: getComputedStyle(document.documentElement).getPropertyValue(`--${x.source}`).trim() || "#1f6f5c", fillOpacity: 0.9 })
      .bindTooltip(`${money(x.price)} · ${esc(x.title)}`)
      .on("click", () => focusCard(x.id))
      .addTo(markers);
  }
}

function focusCard(id) {
  const el = document.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!el) return;
  document.querySelectorAll(".card.focus").forEach((c) => c.classList.remove("focus"));
  el.classList.add("focus");
  el.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---- photos: arrows on each card, and a full-size viewer ----
function showPhoto(galleryEl, photos, i) {
  i = (i + photos.length) % photos.length;
  galleryEl.dataset.i = i;
  const img = galleryEl.querySelector("img");
  img.classList.remove("broken");
  img.src = photos[i];
  galleryEl.querySelector(".pcount").textContent = `${i + 1}/${photos.length}`;
}

const viewer = { photos: [], i: 0, gallery: null };

function openViewer(photos, i, galleryEl) {
  Object.assign(viewer, { photos, i, gallery: galleryEl });
  $("lightbox").hidden = false;
  stepViewer(0);
}

function stepViewer(delta) {
  viewer.i = (viewer.i + delta + viewer.photos.length) % viewer.photos.length;
  $("lbImg").src = viewer.photos[viewer.i];
  $("lbCount").textContent = `${viewer.i + 1} / ${viewer.photos.length}`;
  $("lbPrev").hidden = $("lbNext").hidden = viewer.photos.length < 2;
}

function closeViewer() {
  $("lightbox").hidden = true;
  // Leave the card showing the photo the viewer ended on.
  if (viewer.gallery?.querySelector(".pcount")) showPhoto(viewer.gallery, viewer.photos, viewer.i);
}

$("lbPrev").addEventListener("click", () => stepViewer(-1));
$("lbNext").addEventListener("click", () => stepViewer(1));
$("lbClose").addEventListener("click", closeViewer);
$("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox")) closeViewer(); });
document.addEventListener("keydown", (e) => {
  if ($("lightbox").hidden) return;
  if (e.key === "Escape") closeViewer();
  else if (e.key === "ArrowLeft") stepViewer(-1);
  else if (e.key === "ArrowRight") stepViewer(1);
});
let touchX = null;
$("lightbox").addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
$("lightbox").addEventListener("touchend", (e) => {
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 40) stepViewer(dx < 0 ? 1 : -1);
});

$("list").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const cardEl = btn.closest(".card");
  const id = cardEl.dataset.id;
  const act = btn.dataset.act;
  if (act === "prev" || act === "next" || act === "zoom") {
    const photos = byId.get(id).photos;
    const g = btn.closest(".gallery");
    const i = Number(g.dataset.i);
    if (act === "zoom") openViewer(photos, i, g); else showPhoto(g, photos, i + (act === "next" ? 1 : -1));
    return;
  }
  if (act === "more") { cardEl.classList.toggle("open"); return; }
  const set = { fav, hide: hidden, messaged }[act];
  set.has(id) ? set.delete(id) : set.add(id);
  store.set("fav", [...fav]);
  store.set("hidden", [...hidden]);
  store.set("messaged", [...messaged]);
  render();
});

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  view = b.dataset.view;
  render();
}));

async function init() {
  for (const [key, label] of Object.entries(SOURCES)) {
    $("sources").insertAdjacentHTML("beforeend", `<label><input type="checkbox" value="${key}" checked> ${label}</label>`);
  }
  map = L.map("map", { scrollWheelZoom: true }).setView([38.5816, -121.4944], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
  markers = L.layerGroup().addTo(map);

  const data = await fetch("listings.json", { cache: "no-store" }).then((r) => r.json());
  listings = data.listings;
  byId = new Map(listings.map((x) => [x.id, x]));
  const firstImport = listings.reduce((m, x) => (x.firstSeen < m ? x.firstSeen : m), "9999");
  importCutoff = new Date(new Date(firstImport).getTime() + 864e5).toISOString();

  // One "max drive" filter, sort option and map pin per destination in the data.
  destinations = data.destinations || [];
  for (const d of destinations) {
    $("driveFilters").insertAdjacentHTML("beforeend",
      `<label>Max drive to ${esc(d.label)} <input id="drive_${d.id}" type="number" step="5" min="0" placeholder="min"></label>`);
    $("sort").insertAdjacentHTML("beforeend", `<option value="drive_${d.id}">Closest to ${esc(d.label)}</option>`);
    FILTER_IDS.push(`drive_${d.id}`);
    L.marker([d.lat, d.lon], { title: d.name, zIndexOffset: 1000 })
      .bindTooltip(`★ ${esc(d.label)}`, { permanent: true, direction: "top", offset: [-15, -12] })
      .addTo(map);
  }
  restoreFilters();
  document.querySelector(".filters").addEventListener("input", () => { saveFilters(); render(); });
  const updated = new Date(data.updatedAt);
  const newCount = listings.filter(isNew).length;
  $("meta").textContent = `${listings.length} listings · updated ${updated.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` +
    (lastVisit ? ` · ${newCount} new since your last visit` : "");
  render();
  // Mark this visit after a short delay so a quick reload doesn't clear the "New" badges.
  setTimeout(() => store.set("lastVisit", data.updatedAt), 60000);
}

init().catch((e) => { $("meta").textContent = "Couldn't load listings: " + e.message; });
