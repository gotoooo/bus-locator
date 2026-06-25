// 芸陽バス 接近情報 — Webクライアント（MVP）
// バックエンドAPIだけを叩く（フィード直叩き禁止の制約を満たす）。

const AGENCY_ID = 11;
const API = ""; // 同一オリジン配信を想定。別ホストなら "http://localhost:8000" 等に。

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
async function loadDashboard() {
  $("#status").textContent = "更新中…";
  let cards;
  try {
    cards = await api("/dashboard");
  } catch (e) {
    $("#status").textContent = "取得失敗: " + e.message;
    return;
  }
  const root = $("#cards");
  root.innerHTML = "";
  $("#empty-hint").style.display = cards.length ? "none" : "block";

  for (const c of cards) {
    const card = el("div", "card");
    const title = el("h3");
    title.append(el("span", null, c.stopName || c.stopId));
    const del = el("button", "delete", "🗑");
    del.onclick = async (ev) => {
      ev.stopPropagation();
      await api(`/favorites/${c.favoriteId}`, { method: "DELETE" });
      loadDashboard();
    };
    title.append(del);
    card.append(title);

    for (const al of c.alerts || []) {
      card.append(el("div", "alert", "⚠ " + (al.header || al.description || "運行情報あり")));
    }

    if (c.arrivals.length === 0) {
      card.append(el("div", "servicestatus", SERVICE_LABEL[c.serviceStatus] || "直近の便はありません"));
    } else {
      c.arrivals.slice(0, 3).forEach((a) => card.append(renderArrival(a)));
    }
    card.onclick = () => openDetail(c);
    root.append(card);
  }
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
    addRouteOption(box, s.stopId, { route: "すべての路線・方面", routeId: null, directionId: null });
    routes.forEach((r) => addRouteOption(box, s.stopId, r));
    root.append(box);
  }
}
function addRouteOption(box, stopId, r) {
  const opt = el("div", "route-opt");
  const label = r.routeId
    ? `[${r.route}] ${r.headsign || ""}方面`
    : r.route;
  opt.append(el("span", null, label));
  const btn = el("button", null, "＋登録");
  btn.onclick = async () => {
    await api("/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stopId, agencyId: AGENCY_ID,
        routeId: r.routeId, directionId: r.directionId,
      }),
    });
    btn.textContent = "登録済み ✓";
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
