// 通勤バス — Webクライアント（才の瀬 ⇄ 日下橋 専用）
// バックエンドAPIだけを叩く（フィード直叩き禁止の制約を満たす）。

const AGENCY_ID = 11;
const API = (window.__API_BASE__ || localStorage.getItem("apiBase") || "")
  .replace(/\/$/, "");
const COMMUTE = window.__COMMUTE__ || [
  { label: "往路　才の瀬 → 日下橋", from: "才の瀬", to: "日下橋" },
  { label: "復路　日下橋 → 才の瀬", from: "日下橋", to: "才の瀬" },
];

const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};

async function api(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

// ── 表示ラベル ────────────────────────────────────────────
const SERVICE_LABEL = {
  in_service: "",
  before_service: "始発前です",
  finished: "本日の運行は終了しました",
  no_service: "本日この区間の便はありません",
  no_realtime: "リアルタイム情報が取得できません（定刻案内）",
};
const SOURCE_LABEL = { predict: "リアルタイム予測", delay: "定刻+遅延", schedule: "定刻のみ" };

function etaText(a) {
  if (a.imminent) return "まもなく";
  const m = Math.round(a.eta_minutes);
  return m <= 0 ? "まもなく" : `${m}分`;
}
// 運行状態の表示。走行中は「あと○駅」、未出庫は「発車前」。
function stopsText(a) {
  if (!a.running) return "発車前";
  if (a.stops_away === null || a.stops_away === undefined) return "運行中";
  return a.stops_away <= 0 ? "まもなく到着" : `あと${a.stops_away}駅`;
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
  if (a.running && a.current_stop_name) {
    sub.append(el("span", "curstop", `現在 ${a.current_stop_name}付近`));
  }
  sub.append(el("span", `badge ${a.source}`, SOURCE_LABEL[a.source]));
  row.append(sub);

  return row;
}

// ── 往復カード ────────────────────────────────────────────
async function loadCommute() {
  $("#status").textContent = "更新中…";
  const root = $("#commute");
  const results = await Promise.allSettled(
    COMMUTE.map((c) => api(`/commute?agencyId=${AGENCY_ID}` +
      `&from=${encodeURIComponent(c.from)}&to=${encodeURIComponent(c.to)}`))
  );

  root.innerHTML = "";
  results.forEach((res, i) => {
    const leg = COMMUTE[i];
    const card = el("div", "card");
    card.append(el("h3", null, leg.label));

    if (res.status === "rejected") {
      card.append(el("div", "servicestatus", "取得失敗: " + (res.reason?.message || res.reason)));
      root.append(card);
      return;
    }
    const c = res.value;
    const board = c.arrivals[0]?.board_stop_name;
    if (board) card.append(el("div", "board", `🚏 ${board} から乗車`));

    for (const al of c.alerts || []) {
      card.append(el("div", "alert", "⚠ " + (al.header || al.description || "運行情報あり")));
    }
    if (c.arrivals.length === 0) {
      card.append(el("div", "servicestatus", SERVICE_LABEL[c.serviceStatus] || "直近の便はありません"));
    } else {
      c.arrivals.slice(0, 3).forEach((a) => card.append(renderArrival(a)));
      card.onclick = () => openDetail(leg, c);
    }
    root.append(card);
  });
  $("#status").textContent = "最終更新 " + new Date().toLocaleTimeString("ja-JP");
}

$("#refresh").onclick = loadCommute;

// ── 自動更新（最短15秒）──────────────────────────────────
let timer = null;
function setAuto(on) {
  if (timer) clearInterval(timer);
  if (on) timer = setInterval(loadCommute, 15000);
}
$("#autorefresh").onchange = (e) => setAuto(e.target.checked);

// ── 詳細（地図つき）──────────────────────────────────────
let map = null, markers = [];
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

function openDetail(leg, c) {
  $("#detail-title").textContent = leg.label;
  $("#detail").classList.remove("hidden");
  const list = $("#detail-arrivals");
  list.innerHTML = "";
  if (c.arrivals.length === 0) {
    list.append(el("div", "servicestatus", SERVICE_LABEL[c.serviceStatus] || "直近の便はありません"));
  }
  c.arrivals.forEach((a) => list.append(renderArrival(a)));
  drawMap(c);
}
$("#detail-close").onclick = () => $("#detail").classList.add("hidden");

function drawMap(c) {
  if (typeof maplibregl === "undefined") {
    $("#map").innerHTML = '<div class="muted" style="padding:12px">地図ライブラリを読み込めませんでした</div>';
    return;
  }
  const withPos = c.arrivals.filter((a) => a.vehicle);
  const board = c.arrivals.find((a) => a.board_lat != null);
  const center =
    (withPos[0]?.vehicle && [withPos[0].vehicle.lon, withPos[0].vehicle.lat]) ||
    (board && [board.board_lon, board.board_lat]) ||
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

  // 乗車バス停（青ピン）
  if (board) {
    markers.push(new maplibregl.Marker({ color: "#3366cc" })
      .setLngLat([board.board_lon, board.board_lat])
      .setPopup(new maplibregl.Popup().setText("🚏 " + (board.board_stop_name || "乗車バス停")))
      .addTo(map));
  }
  // 走行中車両（緑ピン）
  withPos.forEach((a) => {
    markers.push(new maplibregl.Marker({ color: "#2aa84a" })
      .setLngLat([a.vehicle.lon, a.vehicle.lat])
      .setPopup(new maplibregl.Popup().setText(`🚌 ${a.route} ${a.headsign}方面 ${etaText(a)}`))
      .addTo(map));
  });
}

// ── 起動 ──────────────────────────────────────────────────
loadCommute();
setAuto(true);
