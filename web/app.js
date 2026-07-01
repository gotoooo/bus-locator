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
function hhmm(epochSec) {
  return new Date(epochSec * 1000).toLocaleTimeString("ja-JP", {
    hour: "2-digit", minute: "2-digit",
  });
}
// 定刻との差（遅れ/早発）。{cls, txt} を返す。RT無しは null。
function delayInfo(a) {
  if (a.delay_sec === null || a.delay_sec === undefined) return null;
  const m = Math.round(Math.abs(a.delay_sec) / 60);
  if (Math.abs(a.delay_sec) < 60) return { cls: "ontime", txt: "ほぼ定刻" };
  if (a.delay_sec > 0) return { cls: "late", txt: `+${m}分 遅れ` };
  return { cls: "early", txt: `−${m}分 早発` };
}

function renderArrival(a) {
  const row = el("div", "arr");

  const main = el("div", "arr-main");
  main.append(el("span", "route", a.route || a.route_id));
  main.append(el("span", "head", `${a.headsign || ""}方面`));
  main.append(el("span", "eta" + (a.imminent ? " imminent" : ""), etaText(a)));
  row.append(main);

  const sub = el("div", "arr-sub");
  sub.append(el("span", "sched", `定刻 ${hhmm(a.scheduled_epoch)}`));
  const d = delayInfo(a);
  if (d) sub.append(el("span", `delay ${d.cls}`, d.txt));
  sub.append(el("span", "stops", stopsText(a)));
  sub.append(el("span", `badge ${a.source}`, SOURCE_LABEL[a.source]));
  row.append(sub);

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
  // 同名バス停（のりば違い）を見分けられるよう、行き先を併記する
  for (const s of stops) {
    const box = el("div", "result");
    const routes = await api(`/stops/${encodeURIComponent(s.stopId)}/routes?agencyId=${AGENCY_ID}`);
    const allHeads = [...new Set(routes.map((r) => r.headsign).filter(Boolean))];

    const head = el("div", "name", s.name);
    if (allHeads.length) {
      head.append(el("span", "stop-hint", ` ▶ ${allHeads.slice(0, 4).join("・")}方面`));
    }
    box.append(head);

    // 路線ごとではなく「方向（上り/下り）」だけを選べるようにする。
    // その方向を通る全路線を対象に登録する（routeId は指定しない）。
    const byDir = {};
    routes.forEach((r) => {
      const key = r.directionId ?? "";
      (byDir[key] ||= []).push(r);
    });
    const dirs = Object.keys(byDir).sort();
    if (dirs.length === 0) {
      addDirOption(box, s, null, []);            // 路線情報なし → 全便
    } else {
      dirs.forEach((dir) => {
        const heads = [...new Set(byDir[dir].map((r) => r.headsign).filter(Boolean))];
        addDirOption(box, s, dir, heads);
      });
    }
    root.append(box);
  }
}

// direction_id → 上り/下り。0/1 の対応は事業者により異なるため、行き先ヒントも併記する。
function dirLabel(dir) {
  if (dir === "0") return "上り";
  if (dir === "1") return "下り";
  return dir ? `方向${dir}` : "全方面";
}

function addDirOption(box, stop, dir, heads) {
  const opt = el("div", "route-opt");
  const headHint = heads.length ? `（${heads.slice(0, 3).join("・")}方面）` : "";
  opt.append(el("span", null, dirLabel(dir) + headHint));
  const btn = el("button", null, "＋登録");
  btn.onclick = () => {
    const added = addFav({
      agencyId: AGENCY_ID,
      stopId: stop.stopId,
      stopName: stop.name,
      routeId: null,                              // 路線は絞らない（方向のみ）
      directionId: dir || null,
      routeLabel: dirLabel(dir) + (heads.length ? `・${heads[0]}方面` : ""),
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

// 実際の道路が見えるOSMラスタタイル（APIキー不要）。個人利用の低頻度想定。
const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

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
  // 中心: 車両があればその位置、無ければバス停の位置、どちらも無ければ西条
  const center =
    (withPos[0]?.vehicle && [withPos[0].vehicle.lon, withPos[0].vehicle.lat]) ||
    (card.stopLat != null && [card.stopLon, card.stopLat]) ||
    [132.74, 34.42];

  if (!map) {
    map = new maplibregl.Map({ container: "map", style: OSM_STYLE, center, zoom: 15 });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  } else {
    map.setStyle(OSM_STYLE);
    map.jumpTo({ center, zoom: 15 });
  }
  markers.forEach((m) => m.remove());
  markers = [];

  // バス停マーカー（青）
  if (card.stopLat != null && card.stopLon != null) {
    const stopMarker = new maplibregl.Marker({ color: "#3366cc" })
      .setLngLat([card.stopLon, card.stopLat])
      .setPopup(new maplibregl.Popup().setText("🚏 " + (card.stopName || "バス停")))
      .addTo(map);
    markers.push(stopMarker);
  }

  // 走行中車両マーカー（緑）
  withPos.forEach((a) => {
    const m = new maplibregl.Marker({ color: "#2aa84a" })
      .setLngLat([a.vehicle.lon, a.vehicle.lat])
      .setPopup(new maplibregl.Popup().setText(`🚌 ${a.route} ${a.headsign}方面 ${etaText(a)}`))
      .addTo(map);
    markers.push(m);
  });
}

// ── 起動 ──────────────────────────────────────────────────
loadDashboard();
setAuto(true);
