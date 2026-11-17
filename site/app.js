// Sacramento Rentals: renders site/listings.json with filters, a map, and saved/hidden lists.
// Saved/hidden state and filters live in this browser's localStorage only.

const $ = (id) => document.getElementById(id);
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};

const SOURCES = { zillow: "Zillow", craigslist: "Craigslist", facebook: "Facebook" };
const FILTER_IDS = ["maxPrice", "minBeds", "dogs", "sort", "q", "newOnly", "noPrice", "hideHotels", "hideFlagged"];

let listings = [];
let view = "all";
let fav = new Set(store.get("fav", []));
let hidden = new Set(store.get("hidden", []));
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

function filtered() {
  const f = readFilters();
  const q = f.q.trim().toLowerCase();
  let out = listings.filter((x) => {
    if (view === "fav") return fav.has(x.id);
    if (view === "hidden") return hidden.has(x.id);
    if (hidden.has(x.id)) return false;
    if (!(x.sources || [x.source]).some((s) => f.sources.includes(s))) return false;
    if (x.price == null ? !f.noPrice : x.price > f.maxPrice) return false;
    if (f.minBeds > 0 && x.beds != null && x.beds < f.minBeds) return false;
    const d = dogsOk(x);
    if (f.dogs === "yes" && d !== true) return false;
    if (f.dogs === "maybe" && d === false) return false;
    if (f.hideHotels && x.weeklyHotel) return false;
    if (f.hideFlagged && x.scamFlags?.length) return false;
    if (f.newOnly && !isNew(x)) return false;
    if (q && !`${x.title} ${x.neighborhood} ${x.address} ${x.description}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const price = (x) => x.price ?? Infinity;
  if (f.sort === "priceAsc") out.sort((a, b) => price(a) - price(b));
  else if (f.sort === "priceDesc") out.sort((a, b) => (b.price ?? -1) - (a.price ?? -1));
  else out.sort((a, b) => (b.postedAt || b.firstSeen).localeCompare(a.postedAt || a.firstSeen));
  return out;
}

function readFilters() {
  return {
    maxPrice: Number($("maxPrice").value) || Infinity,
    minBeds: Number($("minBeds").value),
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
    if (!(id in f)) continue;
    const el = $(id);
    if (el.type === "checkbox") el.checked = f[id]; else el.value = f[id];
  }
  document.querySelectorAll("#sources input").forEach((i) => { i.checked = !f.sources || f.sources.includes(i.value); });
}

function ago(iso) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso)) / 864e5);
  return days <= 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

function money(n) { return n == null ? "Price not listed" : "$" + Math.round(n).toLocaleString() + "/mo"; }

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function card(x) {
  const specs = [x.beds != null && (x.beds === 0 ? "Studio" : `${x.beds} bd`), x.baths != null && `${x.baths} ba`, x.sqft && `${Math.round(x.sqft)} sqft`].filter(Boolean).join(" · ");
  const where = [x.neighborhood, x.address].filter(Boolean).join(" — ");
  const badges = [
    isNew(x) && `<span class="badge new">New</span>`,
    ...(x.sources || [x.source]).map((s) => `<span class="badge src-${s}">${SOURCES[s] || s}${s === x.source && x.group ? " · " + esc(x.group.split(/[|,]/)[0].trim()) : ""}</span>`),
    dogsOk(x) === true && `<span class="badge">Dogs OK</span>`,
    x.moveIn && `<span class="badge">Move-in ${esc(x.moveIn)}</span>`,
    x.alsoAt?.length && `<span class="badge">Posted ${x.alsoAt.length + 1}×</span>`,
    ...(x.scamFlags || []).map((f) => `<span class="badge warn">⚠ ${esc(f)}</span>`),
  ].filter(Boolean).join("");
  const photo = x.photos?.[0]
    ? `<img class="photo" loading="lazy" src="${esc(x.photos[0])}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'photo nophoto',textContent:'No photo'}))">`
    : `<div class="photo nophoto">No photo</div>`;
  const copies = (x.alsoAt || []).map((c, i) =>
    `<a href="${esc(c.url)}" target="_blank" rel="noopener">${c.source && c.source !== x.source ? SOURCES[c.source] + " ↗" : `copy ${i + 2}`}</a>`).join(" ");
  return `<li class="card" id="c-${CSS.escape(x.id)}" data-id="${esc(x.id)}">
    ${photo}
    <div>
      <div class="top"><span class="price">${money(x.price)}</span><span class="specs">${specs}</span><span class="specs">${x.postedAt ? "posted " + ago(x.postedAt) : "first seen " + ago(x.firstSeen)}</span></div>
      <p class="title">${esc(x.title)}</p>
      ${where ? `<p class="where">${esc(where)}</p>` : ""}
      <div class="badges">${badges}</div>
      ${x.description ? `<p class="desc">${esc(x.description)}</p>` : ""}
      <div class="actions">
        <a href="${esc(x.url)}" target="_blank" rel="noopener">${x.sources?.length > 1 ? SOURCES[x.source] : "Open listing"} ↗</a> ${copies}
        <button data-act="fav" class="${fav.has(x.id) ? "on" : ""}">${fav.has(x.id) ? "★ Saved" : "☆ Save"}</button>
        <button data-act="hide">${hidden.has(x.id) ? "Unhide" : "Hide"}</button>
        ${x.description ? `<button data-act="more">More</button>` : ""}
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

$("list").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const cardEl = btn.closest(".card");
  const id = cardEl.dataset.id;
  if (btn.dataset.act === "more") { cardEl.classList.toggle("open"); return; }
  const set = btn.dataset.act === "fav" ? fav : hidden;
  set.has(id) ? set.delete(id) : set.add(id);
  store.set("fav", [...fav]);
  store.set("hidden", [...hidden]);
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
  restoreFilters();
  document.querySelector(".filters").addEventListener("input", () => { saveFilters(); render(); });

  map = L.map("map", { scrollWheelZoom: true }).setView([38.5816, -121.4944], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
  markers = L.layerGroup().addTo(map);

  const data = await fetch("listings.json", { cache: "no-store" }).then((r) => r.json());
  listings = data.listings;
  const updated = new Date(data.updatedAt);
  const newCount = listings.filter(isNew).length;
  $("meta").textContent = `${listings.length} listings · updated ${updated.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` +
    (lastVisit ? ` · ${newCount} new since your last visit` : "");
  render();
  // Mark this visit after a short delay so a quick reload doesn't clear the "New" badges.
  setTimeout(() => store.set("lastVisit", data.updatedAt), 60000);
}

init().catch((e) => { $("meta").textContent = "Couldn't load listings: " + e.message; });
