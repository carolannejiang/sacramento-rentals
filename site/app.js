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
const FILTER_IDS = ["maxPrice", "minBeds", "homeType", "minSqft", "listedBy", "minWalk", "postedWithin", "dogs", "sort", "q", "newOnly", "noPrice", "hideHotels", "hideFlagged"];

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
    if (view === "fav") return inMarkedView("fav", x.id);
    if (view === "messaged") return inMarkedView("messaged", x.id);
    if (view === "hidden") return hidden.has(x.id);
    if (hidden.has(x.id)) return false;
    if (!(x.sources || [x.source]).some((s) => f.sources.includes(s))) return false;
    if (x.price == null ? !f.noPrice : x.price > f.maxPrice) return false;
    if (f.minBeds > 0 && x.beds != null && x.beds < f.minBeds) return false;
    if (f.homeType !== "any" && !TYPE_GROUPS[f.homeType].includes(x.unitType)) return false;
    // Unknown posters are left out of both choices: only show what's actually known.
    if (f.listedBy !== "any" && x.listedBy !== f.listedBy) return false;
    // Like "Listed by", a walkability filter only shows listings whose surroundings are known.
    if (f.minWalk && !(x.walk?.score >= f.minWalk)) return false;
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
  } else if (f.sort === "walk") {
    out.sort((a, b) => (b.walk?.score ?? -1) - (a.walk?.score ?? -1));
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
    minWalk: Number($("minWalk").value),
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

function walkClass(score) {
  return score >= 70 ? "very" : score >= 50 ? "walkable" : score >= 25 ? "somewhat" : "car";
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
    whoMarked("messaged", x.id).length && `<span class="badge messaged">✉ Contacted: ${esc(whoMarked("messaged", x.id).join(", "))}</span>`,
    whoMarked("fav", x.id).filter((n) => n !== "You").length &&
      `<span class="badge saved-by">★ ${esc(whoMarked("fav", x.id).filter((n) => n !== "You").join(", "))}</span>`,
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
  const pi = Math.min(photoIndex.get(x.id) || 0, Math.max(0, n - 1));
  const photo = n
    ? `<div class="gallery" data-i="${pi}">
        <span class="nophoto-text">Photo unavailable</span>
        <img class="photo" loading="lazy" src="${esc(x.photos[pi])}" alt="" data-act="zoom" onerror="this.classList.add('broken')">
        ${n > 1 ? `<button class="nav prev" data-act="prev" aria-label="Previous photo">‹</button>
          <button class="nav next" data-act="next" aria-label="Next photo">›</button>
          <span class="pcount">${pi + 1}/${n}</span>` : ""}
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
  const hasMore = x.description || featureList || x.specialOffer || x.alsoAt?.length;
  // Other platforms get a link in the action row; repeat posts on the same platform are listed under Details.
  const otherSources = [...new Map((x.alsoAt || []).filter((c) => c.source && c.source !== x.source).map((c) => [c.source, c])).values()];
  const copies = otherSources.map((c) => `<a href="${esc(c.url)}" target="_blank" rel="noopener">${SOURCES[c.source]} ↗</a>`).join(" ");
  const repeats = (x.alsoAt || []).filter((c) => !c.source || c.source === x.source);
  const repeatList = repeats.length
    ? `<p class="repeats">Also posted ${repeats.length} other time${repeats.length > 1 ? "s" : ""}: ${repeats.map((c, i) =>
        `<a href="${esc(c.url)}" target="_blank" rel="noopener">${i + 1}</a>`).join(" ")}</p>` : "";
  return `<li class="card" id="c-${CSS.escape(x.id)}" data-id="${esc(x.id)}">
    <div class="corner">
      <button data-act="fav" class="icon star ${fav.has(x.id) ? "on" : ""}" aria-pressed="${fav.has(x.id)}" aria-label="Save" title="${fav.has(x.id) ? "Saved" : "Save"}">${fav.has(x.id) ? "★" : "☆"}</button>
      <button data-act="messaged" class="icon check ${messaged.has(x.id) ? "on" : ""}" aria-pressed="${messaged.has(x.id)}" aria-label="Contacted" title="${messaged.has(x.id) ? "Contacted" : "Mark as contacted"}">${messaged.has(x.id) ? "☑" : "☐"}</button>
      <button data-act="hide" class="icon hide" aria-label="${hidden.has(x.id) ? "Unhide" : "Hide"}" title="${hidden.has(x.id) ? "Unhide" : "Hide"}">${hidden.has(x.id) ? "↩" : "✕"}</button>
    </div>
    ${photo}
    <div>
      <div class="top"><span class="price">${money(x.price)}</span><span class="specs">${specs}</span></div>
      <p class="title">${esc(x.title)}</p>
      ${where ? `<p class="where">${esc(where)}</p>` : ""}
      <p class="drive">${drives || "🚗 Location not listed"}</p>
      ${x.walk ? `<p class="walk" title="Within a 10-minute walk: ${x.walk.food} restaurants & cafés, ${x.walk.shops} shops, ${x.walk.parks} parks; ${x.walk.transit} transit stops within 5 minutes">🚶 <b class="walk-${walkClass(x.walk.score)}">${esc(x.walk.label)}</b> (${x.walk.score}) · ${x.walk.amenities} shops & restaurants within 10 min${x.walk.groceryMi != null ? ` · grocery ${x.walk.groceryMi} mi` : ""}</p>` : ""}
      <div class="badges">${badges}</div>
      ${highlights.length ? `<div class="highlights">${highlights.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
      ${x.description ? `<p class="desc">${esc(x.description)}</p>` : ""}
      <div class="details">
        ${x.specialOffer ? `<p class="offer">🎁 ${esc(x.specialOffer)}</p>` : ""}
        ${featureList ? `<dl class="features">${featureList}</dl>` : ""}
        ${repeatList}
      </div>
    </div>
    <div class="actions">
      <span class="posted" title="${x.postedAt ? "Date the listing was posted" : "The source doesn't give a post date"}">${
        x.postedAt ? "Posted " + day(x.postedAt) : postedDate(x) ? "First seen " + day(x.firstSeen) : "Post date not listed"}</span>
      <span class="links">
        ${hasMore ? `<button data-act="more">Expand</button>` : ""}
        ${copies}
        <a href="${esc(x.url)}" target="_blank" rel="noopener">${x.sources?.length > 1 ? SOURCES[x.source] : "Open listing"} ↗</a>
      </span>
    </div>
  </li>`;
}

function render() {
  const rows = filtered();
  $("count").innerHTML = `${rows.length} listing${rows.length === 1 ? "" : "s"}<span class="keys"> · Keys: ↑↓ listing · ←→ photos · S star · X hide</span>`;
  $("list").innerHTML = rows.slice(0, 400).map(card).join("") + (rows.length > 400 ? `<li class="count">Showing first 400 — narrow the filters to see more.</li>` : "");
  $("favCount").textContent = fav.size ? `(${fav.size})` : "";
  $("hiddenCount").textContent = hidden.size ? `(${hidden.size})` : "";
  $("messagedCount").textContent = messaged.size ? `(${messaged.size})` : "";
  markers.clearLayers();
  markerById.clear();
  hovered = null;
  for (const x of rows) {
    if (x.lat == null || x.lon == null) continue;
    const m = L.circleMarker([x.lat, x.lon], dotStyle(x.source))
      .bindTooltip(`${money(x.price)} · ${esc(x.title)}`)
      .on("click", () => focusCard(x.id))
      .addTo(markers);
    m.source = x.source;
    markerById.set(x.id, m);
  }
  if (cardEl(selectedId)) {
    cardEl(selectedId).classList.add("focus");
    highlight(selectedId);
  }
}

// ---- heatmap of shops & restaurants (OpenStreetMap), toggled from the map's corner ----
// About 250 m around each place, whatever the zoom level.
function heatSize() {
  const metersPerPixel = 156543 * Math.cos((map.getCenter().lat * Math.PI) / 180) / 2 ** map.getZoom();
  const radius = Math.max(8, Math.min(80, 250 / metersPerPixel));
  return { radius, blur: radius * 0.9 };
}

function initHeatmap() {
  let layer = null;
  map.createPane("heat");
  map.getPane("heat").style.zIndex = 350; // below the dots (overlay pane is 400)
  map.getPane("heat").style.pointerEvents = "none";
  const control = L.control({ position: "topright" });
  control.onAdd = () => {
    const div = L.DomUtil.create("label", "heat-toggle");
    div.innerHTML = `<span><input type="checkbox"> Shops & restaurants</span>
      <span class="heat-legend"><i></i>fewer → more</span>`;
    L.DomEvent.disableClickPropagation(div);
    const box = div.querySelector("input");
    box.checked = store.get("heatmap", false);
    const showLegend = () => div.classList.toggle("on", box.checked);
    box.addEventListener("change", showLegend);
    showLegend();
    const apply = async () => {
      store.set("heatmap", box.checked);
      if (box.checked && !layer) {
        const points = await fetch("places.json").then((r) => r.json()).catch(() => []);
        layer = L.heatLayer(points, { ...heatSize(), maxZoom: 13, minOpacity: 0.3,
          gradient: { 0.2: "#fde2b6", 0.5: "#f8b26a", 0.8: "#ef7d3c", 1: "#c2410c" } });
        // Blobs are sized in pixels; grow them as you zoom in so they keep covering whole blocks.
        map.on("zoomend", () => layer.setOptions(heatSize()));
      }
      if (!layer) return;
      if (!box.checked) return layer.remove();
      layer.addTo(map);
      // Leaflet.heat draws into the same pane as the listing dots; move it underneath them.
      map.getPane("heat").appendChild(layer._canvas);
    };
    box.addEventListener("change", apply);
    if (box.checked) apply();
    return div;
  };
  control.addTo(map);
}

// ---- hovering a listing highlights its dot and grays out the rest ----
const markerById = new Map();
let hovered = null;

function dotStyle(source) {
  const color = getComputedStyle(document.documentElement).getPropertyValue(`--${source}`).trim() || "#1f6f5c";
  return { radius: 6, weight: 1, color: "#fff", fillColor: color, fillOpacity: 0.9 };
}

function highlight(id) {
  if (id === hovered) return;
  hovered = id;
  const target = id && markerById.get(id);
  for (const m of markerById.values()) {
    m.setStyle(!target ? dotStyle(m.source)
      : m === target ? { radius: 10, weight: 3, color: "#fff", fillColor: "#e8590c", fillOpacity: 1 }
      : { radius: 5, weight: 0, fillColor: "#9a9a96", fillOpacity: 0.25 });
  }
  if (target) {
    target.bringToFront();
    if (!map.getBounds().pad(-0.05).contains(target.getLatLng())) map.panTo(target.getLatLng());
  }
}

// Gaps between cards keep the last highlight, so it doesn't flicker while moving down the list.
$("list").addEventListener("mouseover", (e) => { const id = e.target.closest(".card")?.dataset.id; if (id) highlight(id); });
$("list").addEventListener("mouseleave", () => highlight(cardEl(selectedId) ? selectedId : null));

// ---- the selected listing: set by clicking a card or a map dot, or with the arrow keys ----
let selectedId = null;

function cardEl(id) { return id && document.querySelector(`.card[data-id="${CSS.escape(id)}"]`); }

function selectCard(id, block = "center") {
  const el = cardEl(id);
  if (!el) return;
  document.querySelectorAll(".card.focus").forEach((c) => c.classList.remove("focus"));
  el.classList.add("focus");
  selectedId = id;
  highlight(id);
  el.scrollIntoView({ behavior: "smooth", block });
}

function focusCard(id) { selectCard(id); }

// Keys: ↑/↓ listing · ←/→ (or < >) photos · S star · X hide. Ignored while typing in a field.
document.addEventListener("keydown", (e) => {
  if (!$("lightbox").hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target.closest?.("input, select, textarea, [contenteditable]")) return;
  const cards = [...document.querySelectorAll("#list .card")];
  if (!cards.length) return;
  const current = cardEl(selectedId) && cards.includes(cardEl(selectedId)) ? cardEl(selectedId) : null;
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (key === "ArrowDown" || key === "ArrowUp") {
    e.preventDefault();
    const i = current ? cards.indexOf(current) + (key === "ArrowDown" ? 1 : -1) : 0;
    selectCard(cards[Math.max(0, Math.min(cards.length - 1, i))].dataset.id, "nearest");
  } else if (["ArrowLeft", "ArrowRight", ",", ".", "<", ">"].includes(key)) {
    const target = current || cards[0];
    if (!current) selectCard(target.dataset.id, "nearest");
    const nav = target.querySelector(["ArrowRight", ".", ">"].includes(key) ? ".gallery .next" : ".gallery .prev");
    if (nav) { e.preventDefault(); nav.click(); }
  } else if ((key === "s" || key === "x") && current) {
    e.preventDefault();
    const id = current.dataset.id;
    const next = cards[cards.indexOf(current) + 1] || cards[cards.indexOf(current) - 1];
    current.querySelector(key === "s" ? '[data-act="fav"]' : '[data-act="hide"]').click();
    // Hiding removes the card from the list, so move on to the next one.
    if (key === "x" && !cardEl(id) && next) selectCard(next.dataset.id, "nearest");
    else selectCard(id, "nearest");
  }
});

// ---- photos: arrows on each card, and a full-size viewer ----
// Which photo each listing is on, so starring or hiding (which redraws the list) keeps it.
const photoIndex = new Map();

function showPhoto(galleryEl, photos, i) {
  i = (i + photos.length) % photos.length;
  galleryEl.dataset.i = i;
  photoIndex.set(galleryEl.closest(".card").dataset.id, i);
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
  const clicked = e.target.closest(".card");
  if (clicked && !e.target.closest("a")) selectedId = clicked.dataset.id;
  const btn = e.target.closest("[data-act]");
  if (!btn) {
    if (clicked && !e.target.closest("a")) selectCard(clicked.dataset.id, "nearest");
    return;
  }
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
  if (act === "more") {
    btn.textContent = cardEl.classList.toggle("open") ? "Collapse" : "Expand";
    return;
  }
  const name = { fav: "fav", hide: "hidden", messaged: "messaged" }[act];
  const set = markSets()[name];
  const on = !set.has(id);
  on ? set.add(id) : set.delete(id);
  saveMarksLocally();
  pushMark(name, id, on);
  render();
});

// ---- accounts: marks belong to a name + passcode, and everyone sees each other's saves ----
// Signed out, marks stay in this browser. Signed in, your marks live on the server under your
// account (so they follow you to any device), and other people's saved and contacted
// listings are shown too. Hidden listings are only ever your own.
const SYNC_URL = "https://sacramento-rentals.vercel.app/api/marks";
let account = store.get("account", null); // { name, passcode }
let syncState = "off"; // off | ok | bad | error
let others = {}; // slug -> { name, fav: Set, messaged: Set }

function markSets() { return { fav, hidden, messaged }; }

function saveMarksLocally() {
  if (account) return; // signed in: the server is the copy that matters
  for (const [name, set] of Object.entries(markSets())) store.set(name, [...set]);
}

async function syncRequest(body, creds = account) {
  const r = await fetch(SYNC_URL, {
    method: body ? "POST" : "GET",
    headers: {
      "x-user": encodeURIComponent(creds.name), "x-pass": encodeURIComponent(creds.passcode),
      ...(body ? { "content-type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || `sync ${r.status}`), { status: r.status });
  return data;
}

function pushMark(set, id, on) {
  if (!account) return;
  syncRequest({ set, id, on }).then(() => setSyncState("ok"), () => setSyncState("error"));
}

async function pullMarks() {
  if (!account) return setSyncState("off");
  try {
    const data = await syncRequest();
    const mine = data.marks[data.me.slug] || {};
    for (const [name, set] of Object.entries(markSets())) {
      set.clear();
      (mine[name] || []).forEach((id) => set.add(id));
    }
    others = {};
    for (const p of data.people) {
      if (p.slug === data.me.slug) continue;
      const m = data.marks[p.slug] || {};
      others[p.slug] = { name: p.name, fav: new Set(m.fav || []), messaged: new Set(m.messaged || []) };
    }
    account.name = data.me.name;
    setSyncState("ok");
    renderPeople();
    render();
  } catch (e) { setSyncState(e.status === 401 ? "bad" : "error"); }
}

// Who saved / contacted a listing, as display names ("You" first).
function whoMarked(set, id) {
  const names = markSets()[set].has(id) ? ["You"] : [];
  for (const p of Object.values(others)) if (p[set]?.has(id)) names.push(p.name);
  return names;
}

// For the Saved and Contacted tabs: whose marks to show (me, everyone, or one person).
function inMarkedView(set, id) {
  const who = $("markedBy").value;
  if (who === "me" || !account) return markSets()[set].has(id);
  if (who === "all") return whoMarked(set, id).length > 0;
  return others[who]?.[set]?.has(id) || false;
}

function renderPeople() {
  const sel = $("markedBy");
  const keep = sel.value;
  sel.innerHTML = `<option value="all">Everyone</option><option value="me">Just me</option>` +
    Object.entries(others).map(([slug, p]) => `<option value="${esc(slug)}">${esc(p.name)}</option>`).join("");
  sel.value = [...sel.options].some((o) => o.value === keep) ? keep : "all";
  sel.hidden = !account || !Object.keys(others).length;
}

function setSyncState(s) {
  syncState = s;
  $("syncStatus").textContent = {
    off: "Sign in to save listings to your account and see what friends save.",
    ok: `Signed in as ${account?.name}`,
    bad: "Wrong passcode",
    error: "⚠ Couldn't reach the server; try again",
  }[s];
  $("syncStatus").className = `sync ${s}`;
  $("syncBtn").textContent = account && s !== "bad" ? "Sign out" : "Sign in";
}

async function signIn(name, passcode) {
  try {
    let res;
    try {
      res = await syncRequest({ action: "login" }, { name, passcode });
    } catch (e) {
      if (e.status !== 404) throw e;
      // Names ignore case and spaces, so this only appears for a genuinely new name.
      if (!confirm(`There's no account named "${name}" yet. Create it?`)) return setSyncState(account ? "ok" : "off");
      res = await syncRequest({ action: "login", create: true }, { name, passcode });
    }
    // Marks made in this browser while signed out move into the account.
    const local = Object.fromEntries(Object.entries(markSets()).map(([k, set]) => [k, [...set]]));
    account = { name: res.name, passcode };
    store.set("account", account);
    for (const [set, ids] of Object.entries(local)) for (const id of ids) await syncRequest({ set, id, on: true });
    for (const set of Object.keys(local)) store.set(set, []);
    await pullMarks();
  } catch (e) {
    $("syncStatus").textContent = e.status === 401 ? "Wrong passcode" : e.message;
    $("syncStatus").className = "sync bad";
  }
}

function signOut() {
  account = null;
  store.set("account", null);
  others = {};
  for (const set of Object.values(markSets())) set.clear();
  renderPeople();
  setSyncState("off");
  render();
}

$("syncBtn").addEventListener("click", () => {
  if (account && syncState !== "bad") return signOut();
  $("syncForm").hidden = false;
  $("syncName").focus();
});
$("syncCancel").addEventListener("click", () => { $("syncForm").hidden = true; });
$("syncForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("syncName").value.trim(), passcode = $("syncInput").value;
  if (!name || !passcode) return;
  $("syncForm").hidden = true;
  $("syncInput").value = "";
  await signIn(name, passcode);
});
$("markedBy").addEventListener("change", () => render());
window.addEventListener("focus", () => pullMarks());

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  view = b.dataset.view;
  render();
}));

// ---- drag the bar between map and list to resize them (remembered in this browser) ----
function setMapWidth(pct) {
  pct = Math.min(75, Math.max(20, pct));
  document.querySelector("main").style.setProperty("--map-width", pct + "%");
  $("splitter").setAttribute("aria-valuenow", Math.round(pct));
  map?.invalidateSize();
  return pct;
}

function initSplitter() {
  const bar = $("splitter");
  const main = document.querySelector("main");
  let pct = setMapWidth(store.get("mapWidth", 45));
  bar.addEventListener("pointerdown", (e) => {
    bar.setPointerCapture(e.pointerId);
    bar.classList.add("dragging");
    document.body.classList.add("resizing");
  });
  bar.addEventListener("pointermove", (e) => {
    if (!bar.hasPointerCapture(e.pointerId)) return;
    const r = main.getBoundingClientRect();
    pct = setMapWidth(((e.clientX - r.left) / r.width) * 100);
  });
  const endDrag = () => {
    bar.classList.remove("dragging");
    document.body.classList.remove("resizing");
    store.set("mapWidth", pct);
  };
  bar.addEventListener("pointerup", endDrag);
  bar.addEventListener("lostpointercapture", endDrag);
  bar.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    pct = setMapWidth(pct + (e.key === "ArrowRight" ? 3 : -3));
    store.set("mapWidth", pct);
  });
}

async function init() {
  for (const [key, label] of Object.entries(SOURCES)) {
    $("sources").insertAdjacentHTML("beforeend", `<label><input type="checkbox" value="${key}" checked> ${label}</label>`);
  }
  map = L.map("map", { scrollWheelZoom: true }).setView([38.5816, -121.4944], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
  markers = L.layerGroup().addTo(map);
  initSplitter();
  initHeatmap();

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
  pullMarks();
  // Mark this visit after a short delay so a quick reload doesn't clear the "New" badges.
  setTimeout(() => store.set("lastVisit", data.updatedAt), 60000);
}

init().catch((e) => { $("meta").textContent = "Couldn't load listings: " + e.message; });
