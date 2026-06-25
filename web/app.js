// 芸陽バス 接近情報 — Webクライアント（MVP）
// バックエンドAPIだけを叩く（フィード直叩き禁止の制約を満たす）。

const AGENCY_ID = 11;
// API接続先: config.js の window.__API_BASE__ → localStorage.apiBase → 同一オリジン。
const API = (window.__API_BASE__ || localStorage.getItem("apiBase") || "")
  .replace(/\/$/, "");

const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

// ── お気に入り（端末ローカル保存。サーバDB不要＝どの無料ホストでも消えない）──
const FAV_KEY = "favorites";
function loadFavs() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); }
  catch { return []; }
}
function saveFavs(list) { localStorage.setItem(FAV_KEY, JSON.stringify(list)); }
function favKey(f) {
  return [f.agencyId, f.stopId, f.routeId || "", f.directionId || ""].join("|");
}
function addFav(f) {
  const list = loadFavs();
  if (list.some((x) => favKey(x) === favKey(f))) return false;
  list.push(f); saveFavs(list); return true;
}
function removeFav(key) {
  saveFavs(loadFavs().filter((x) => favKey(x) !== key));
}
function arrivalsUrl(f) {
  const p = new URLSearchParams({ agencyId: f.agencyId, stopId: f.stopId });
  if (f.routeId) p.set("routeId", f.routeId);
  if (f.directionId) p.set("directionId", f.directionId);
  return "/arrivals?" + p.toString();
}

// ── タブ切替 ──────────────────────────────────────────────
document.querySelectorAll(".tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "dashboard") loadDashboard();
  };
});

// ── 状態ラベル ────────────────────────────────────────────
const SERVICE_LABEL = {
  in_service: "",
  before_service: "始発前です",
  finished: "本日の運行は終了しました",
  no_service: "本日この停留所の便はありません",
  no_realtime: "リアルタイム情報が取得できません（定刻案内）",
};
const SOURCE_LABEL = { predict: "リアルタイム予測", delay: "定刻+遅延", schedule: "定刻のみ" };

function etaText(a) {
  if (a.imminent) return "まもなく";
  const m = Math.round(a.eta_minutes);
  return m <= 0 ? "まもなく" : `${m}分`;
}
function stopsText(a) {
  if (a.stops_away === null || a.stops_away === undefined) return "位置情報なし";
  return a.stops_away === 0 ? "まもなく到着" : `あと${a.stops_away}駅`;
}

function renderArrival(a) {
  const row = el("div", "arr");
  row.append(el("span", "route", a.route || a.route_id));
  row.append(el("span", "head", `${a.headsign || ""}方面`));
  row.append(el("span", "stops", stopsText(a)));
  const eta = el("span", "eta" + (a.imminent ? " imminent" : ""), etaText(a));
  row.append(eta);
  row.append(el("span", `badge ${a.source}`, SOURCE_LABEL[a.source]));
  return row;
}

// ── ダッシュボード ────────────────────────────────────────
// 端末に保存した停留所ごとに /arrivals を呼ぶ（サーバは状態を持たない）。
async function loadDashboard() {
  const favs = loadFavs();
  const root = $("#cards");
  root.innerHTML = "";
  $("#empty-hint").style.display = favs.length ? "none" : "block";
  if (!favs.length) { $("#status").textContent = ""; return; }

  $("#status").textContent = "更新中…";
  const results = await Promise.allSettled(favs.map((f) => api(arrivalsUrl(f))));

  results.forEach((res, i) => {
    const f = favs[i];
    const card = el("div", "card");
    const title = el("h3");
    const name = f.routeLabel ? `${f.stopName}（${f.routeLabel}）` : (f.stopName || f.stopId);
    title.append(el("span", null, name));
    const del = el("button", "delete", "🗑");
    del.onclick = (ev) => { ev.stopPropagation(); removeFav(favKey(f)); loadDashboard(); };
    title.append(del);
    card.append(title);

    if (res.status === "rejected") {
      card.append(el("div", "servicestatus", "取得失敗: " + (res.reason?.message || res.reason)));
    } else {
      const c = res.value;
      for (const al of c.alerts || []) {
        card.append(el("div", "alert", "⚠ " + (al.header || al.description || "運行情報あり")));
      }
      if (c.arrivals.length === 0) {
        card.append(el("div", "servicestatus", SERVICE_LABEL[c.serviceStatus] || "直近の便はありません"));
      } else {
        c.arrivals.slice(0, 3).forEach((a) => card.append(renderArrival(a)));
      }
      card.onclick = () => openDetail(c);
    }
    root.append(card);
  });
  $("#status").textContent = "最終更新 " + new Date().toLocaleTimeString("ja-JP");
}

$("#refresh").onclick = loadDashboard;

// ── 自動更新（最短15秒。クライアントはバックエンド経由なので負荷は集約済み）──
let timer = null;
function setAuto(on) {
  if (timer) clearInterval(timer);
  if (on) timer = setInterval(loadDashboard, 15000);
}
$("#autorefresh").onchange = (e) => setAuto(e.target.checked);

// ── 検索・登録 ────────────────────────────────────────────
async function doSearch() {
  const q = $("#q").value.trim();
  if (!q) return;
  const root = $("#search-results");
  root.innerHTML = "検索中…";
  const stops = await api(`/stops?agencyId=${AGENCY_ID}&q=${encodeURIComponent(q)}`);
  root.innerHTML = "";
  if (!stops.length) { root.textContent = "一致するバス停がありません"; return; }
  for (const s of stops) {
    const box = el("div", "result");
    box.append(el("div", "name", s.name));
    const routes = await api(`/stops/${encodeURIComponent(s.stopId)}/routes?agencyId=${AGENCY_ID}`);
    // 「全便」登録
    addRouteOption(box, s, { route: "すべての路線・方面", routeId: null, directionId: null });
    routes.forEach((r) => addRouteOption(box, s, r));
    root.append(box);
  }
}
function addRouteOption(box, stop, r) {
  const opt = el("div", "route-opt");
  const label = r.routeId ? `[${r.route}] ${r.headsign || ""}方面` : r.route;
  opt.append(el("span", null, label));
  const btn = el("button", null, "＋登録");
  btn.onclick = () => {
    const added = addFav({
      agencyId: AGENCY_ID,
      stopId: stop.stopId,
      stopName: stop.name,
      routeId: r.routeId || null,
      directionId: r.directionId ?? null,
      routeLabel: r.routeId ? `${r.route} ${r.headsign || ""}方面` : null,
    });
    btn.textContent = added ? "登録済み ✓" : "登録済み";
    btn.disabled = true;
  };
  opt.append(btn);
  box.append(opt);
}
$("#do-search").onclick = doSearch;
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

// ── 詳細（地図つき）──────────────────────────────────────
let map = null, markers = [];
function openDetail(card) {
  $("#detail-title").textContent = card.stopName || card.stopId;
  $("#detail").classList.remove("hidden");
  const list = $("#detail-arrivals");
  list.innerHTML = "";
  if (card.arrivals.length === 0) {
    list.append(el("div", "servicestatus", SERVICE_LABEL[card.serviceStatus] || "直近の便はありません"));
  }
  card.arrivals.forEach((a) => list.append(renderArrival(a)));
  drawMap(card);
}
$("#detail-close").onclick = () => $("#detail").classList.add("hidden");

function drawMap(card) {
  if (typeof maplibregl === "undefined") {
    $("#map").innerHTML = '<div class="muted" style="padding:12px">地図ライブラリを読み込めませんでした</div>';
    return;
  }
  const withPos = card.arrivals.filter((a) => a.vehicle);
  const center = withPos[0]?.vehicle
    ? [withPos[0].vehicle.lon, withPos[0].vehicle.lat]
    : [132.74, 34.42]; // 西条あたり

  if (!map) {
    map = new maplibregl.Map({
      container: "map",
      style: "https://demotiles.maplibre.org/style.json",
      center, zoom: 12,
    });
  } else {
    map.setCenter(center);
  }
  markers.forEach((m) => m.remove());
  markers = [];
  map.once("idle", () => {});
  withPos.forEach((a) => {
    const m = new maplibregl.Marker({ color: "#2aa84a" })
      .setLngLat([a.vehicle.lon, a.vehicle.lat])
      .setPopup(new maplibregl.Popup().setText(`${a.route} ${a.headsign}方面 ${etaText(a)}`))
      .addTo(map);
    markers.push(m);
  });
}

// ── 起動 ──────────────────────────────────────────────────
loadDashboard();
setAuto(true);
