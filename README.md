# 芸陽バス 接近情報アプリ

芸陽バスのオープンデータ（広島県バス協会オープンデータ / モバイルクリエイト基盤 `id=11`、**ライセンス CC0**）を使い、
登録したバス停の直近の便が **「今どこにいるか・あと何駅・あと何分」** をリアルタイム表示するアプリ。

開発仕様書（`docs` 相当の元文書）に基づく実装。コアロジックの参照実装は `geiyo_bus.py`。

---

## 構成

```
geiyo_bus.py            参照実装（静的取得・RT取得・ETA算出が単体で動く）
backend/
  app/
    providers.py        事業者アダプタ層（多事業者対応の口）
    config.py           設定（環境変数で上書き可）
    fetcher.py          フィード取得（ライブHTTP / ローカルfixture）
    gtfs_static.py      静的GTFS-JP取り込み・検索・運行日判定
    gtfs_realtime.py    GTFS-RT（Vehicle/TripUpdate/Alert）パース
    eta.py              コアロジック: 直近便・あと何駅・あと何分（3段フォールバック）
    poller.py           静的1日1回 + RT 15秒ポーリング・キャッシュ（集約型）
    main.py             FastAPI（自前API + ローカル開発用Webクライアント配信）
  tools/
    make_demo_fixture.py  オフライン用デモGTFS生成
    snapshot_feeds.py     ライブフィードのローカル保存
    make_pwa_icons.py     PWAアイコン生成
  tests/                pytest（ETA / 静的 / API、ネットワーク不要）
web/                    Webクライアント（PWA。検索→登録→ダッシュボード→地図詳細）
  app.js                お気に入りは端末localStorageに保持
  config.js             バックエンドAPIの接続先設定
  manifest.webmanifest  PWAマニフェスト
  sw.js                 Service Worker（シェルはオフライン可・API応答は非キャッシュ）
  icons/                ホーム画面アイコン（make_pwa_icons.py で再生成）
```

### アーキテクチャ方針
- **バックエンド集約型**: RTは15秒更新・高頻度アクセス禁止のため、バックエンドで1回取得しキャッシュして配る（クライアントからフィードを直叩きしない）。
- **ステートレス**: お気に入りはクライアント（PWA）が端末の `localStorage` に保持し、停留所ごとに `/arrivals` を呼ぶ。バックエンドはDBを持たないため、揮発ディスクの無料ホストでも動く。
- **アダプタ層**: フィード取得元を `providers.py` に集約。内部モデルはGTFS標準なのでパーサは共通。新事業者は `Provider` を1つ足すだけ。
- **フォールバック**: RT欠損時は静的の定刻案内へ自動フォールバック（`rtAvailable=false` / `source="schedule"`）。

---

## セットアップ

```bash
cd backend
pip install -r requirements.txt
```

### 起動（ライブ）
芸陽バスのフィードホスト `ajt-mobusta-gtfs.mcapps.jp` に到達できる環境で:

```bash
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/ でWebクライアント
```

### 起動（オフライン / ネットワーク制限環境）
フィードホストに到達できない場合は、デモ静的データで一通り動かせる:

```bash
python tools/make_demo_fixture.py demo_static.zip
STATIC_FIXTURE=$PWD/demo_static.zip uvicorn app.main:app --port 8000
```

実データのスナップショットを使う場合（到達可能な環境で1回取得しておく）:

```bash
python tools/snapshot_feeds.py ./snapshots
STATIC_FIXTURE=./snapshots/current_data.zip \
RT_VEHICLE_FIXTURE=./snapshots/vehicle_position.bin \
RT_TRIP_FIXTURE=./snapshots/trip_updates.bin \
RT_ALERT_FIXTURE=./snapshots/alerts.bin \
uvicorn app.main:app --port 8000
```

### テスト
```bash
cd backend
python -m pytest        # ネットワーク不要（合成GTFSで検証）
```

---

## 本番デプロイ（無料: PWA=Vercel / API=Render 無料枠）

**フロント(PWA)はVercel、API(FastAPI+15秒ポーラ)はRender無料枠**に分離する。
お気に入りは端末localStorageに持つのでバックエンドはステートレス＝無料枠の揮発ディスクでも問題ない。
（フィードはブラウザから直接叩けない＝高頻度アクセス禁止/CORS無しのため、フロント単体では成立しない）

```
[PWA: Vercel(静的/HTTPS)]  ──CORS──▶  [API: Render無料枠(FastAPI+15秒ポーラ)]  ──▶  芸陽バスフィード
```

> **Render無料枠の挙動**: 15分アクセスが無いとスリープし、次回アクセスでコールドスタート（数十秒）。
> 個人利用なら実用上問題なし（見ていない間に止まるだけ）。常時起動が必要なら Oracle Always Free VM 等に置き換え可。

### 1) バックエンドを Render へ
リポジトリをRenderに連携 → **New → Blueprint** → このリポジトリを選ぶと、同梱の `render.yaml` から
Dockerイメージ（`backend/Dockerfile`）でサービスが作られる。
```
→ https://<your-app>.onrender.com が公開URL
```
- 作成後 `https://<your-app>.onrender.com/health` を開き、`"rtOk": true`（フィード疎通）を確認。
- このホストから `ajt-mobusta-gtfs.mcapps.jp` へのアウトバウンドが通る必要あり。
- Railway / Fly.io でも同じ `Dockerfile` で動く（`$PORT` 対応済み）。

### 2) フロント(PWA)の接続先を設定
`web/config.js` の1行をバックエンドURLに:
```js
window.__API_BASE__ = "https://<your-app>.onrender.com";
```

### 3) PWAをVercelへ
リポジトリをVercelに連携し、同梱の `vercel.json`（`outputDirectory: web`）でビルド不要の静的サイトとして配信。
- `vercel.json` が `sw.js` の no-cache と `Service-Worker-Allowed: /`、`manifest` のContent-Typeを付与する。
- VercelはHTTPS標準なので、PWA（Service Worker）がそのまま有効になる。
- スマホでアクセス →「ホーム画面に追加」でアプリ化。

> CORSはバックエンドで全許可済み。絞りたい場合は `main.py` の `allow_origins` をVercelのドメインに変更する。

### ローカルでの一体起動
開発時は分離せず、FastAPIがフロントも同一オリジンで配る（`web/config.js` は空のままでOK）:
```bash
cd backend && uvicorn app.main:app --port 8000   # http://localhost:8000/
```

---

## API（自前）

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | 状態・RT鮮度 |
| GET | `/agencies` | 事業者一覧 |
| GET | `/stops?agencyId=&q=` | バス停名の部分一致検索 |
| GET | `/stops/{stopId}/routes?agencyId=` | その停留所の路線・方面 |
| GET | `/arrivals?agencyId=&stopId=&routeId=&directionId=` | 直近便（eta昇順） |
| GET | `/alerts?agencyId=&routeId=&stopId=` | 運休・迂回Alert |

> お気に入り・ダッシュボードはクライアント側（端末localStorage）で完結するため、サーバAPIは持たない。
> クライアントは登録した停留所ごとに `/arrivals` を呼ぶ。

### `/arrivals` 応答例
```jsonc
{
  "stopId": "1002",
  "stopName": "西条中央",
  "serviceStatus": "in_service",   // in_service|before_service|finished|no_service|no_realtime
  "rtAvailable": true,
  "agencyId": 11,
  "arrivals": [
    {
      "trip_id": "...", "route_id": "R1", "route": "1",
      "headsign": "広島大学", "direction_id": "0",
      "stops_away": 3,             // 位置情報が無ければ null
      "eta_minutes": 7.2,
      "source": "predict",         // predict|delay|schedule
      "source_label": "リアルタイム予測",
      "status": "running",         // running|no_realtime
      "imminent": false,           // 到着直前なら true（「まもなく到着」表示）
      "has_position": true,
      "vehicle": { "lat": 34.42, "lon": 132.74, "bearing": 90 }
    }
  ],
  "alerts": []
}
```

> 仕様書 §6 では `/arrivals` は配列だが、始発前/終バス後などの空状態を表現できるよう
> `serviceStatus` を持つオブジェクトでラップしている（便のリストは `arrivals`）。

---

## コアロジック（`eta.py` / `geiyo_bus.py`）

### あと何分（ETA）— 3段フォールバック
| 優先 | 条件 | 計算 | `source` |
|---|---|---|---|
| 1 | TripUpdate に到着予測 `arrival.time` あり | 予測時刻 − 現在 | `predict` |
| 2 | TripUpdate に `delay` のみ | 定刻 + delay − 現在 | `delay` |
| 3 | RTなし | 定刻 − 現在 | `schedule` |

### あと何駅
`stops_away = 登録stopのstop_sequence − VehiclePositionのcurrent_stop_sequence`
（位置が無い便は `null`、負なら通過済みとして除外）

### 実装済みエッジケース（仕様書 §8）
- 24時超え時刻 `25:30:00`（前日サービスを候補日に含めて算出）
- 始発前 `before_service` / 終バス後 `finished` / 無運行 `no_service`
- RT中断時の定刻フォールバック `no_realtime`
- 環状・循環路線（同一便が同じ停留所を複数回通る出現を個別評価）
- ダイヤ改正（`feed_info.txt` の有効期間で current/latest を切替）
- 到着直前の「まもなく到着」閾値（`imminent`）
- 通過済み・遠すぎる便の除外（既定ホライズン90分）
- trip_id 単位の重複排除

---

## データソースと制約

| 種別 | URL |
|---|---|
| 静的GTFS-JP（当日） | `https://ajt-mobusta-gtfs.mcapps.jp/static/11/current_data.zip` |
| 静的GTFS-JP（改正予定） | `https://ajt-mobusta-gtfs.mcapps.jp/static/11/latest.zip` |
| RT TripUpdate | `https://ajt-mobusta-gtfs.mcapps.jp/realtime/11/trip_updates.bin` |
| RT VehiclePosition | `https://ajt-mobusta-gtfs.mcapps.jp/realtime/11/vehicle_position.bin` |
| RT Alert | `https://ajt-mobusta-gtfs.mcapps.jp/realtime/11/alerts.bin` |

- **RTは15秒更新。ポーリングは最短15秒、高頻度アクセス禁止**（`RT_POLL_INTERVAL_SEC` は15未満にできない）。
- 提供は予告なく中断されうる（免責）。RT欠損時は定刻案内へ自動フォールバック。
- ネットワーク制限環境では当該ホストの許可設定が必要。許可できない場合は上記オフライン手順を使う。

---

## 主な設定（環境変数）

| 変数 | 既定 | 説明 |
|---|---|---|
| `RT_POLL_INTERVAL_SEC` | 15 | RTポーリング間隔（15未満は15に丸め） |
| `STATIC_REFRESH_INTERVAL_SEC` | 86400 | 静的再取得間隔 |
| `ARRIVALS_HORIZON_MIN` | 90 | 直近便の探索ホライズン（分） |
| `IMMINENT_THRESHOLD_MIN` | 1.0 | 「まもなく到着」閾値（分） |
| `ENABLE_POLLER` | 1 | 起動時のRTポーリング有無 |
| `STATIC_FIXTURE` / `RT_*_FIXTURE` | — | ローカルファイルから読む（オフライン開発） |

---

## PWA（個人利用向け）

Webクライアントはインストール可能な **PWA** です。スマホのブラウザで開き「ホーム画面に追加」すると、
全画面のアプリとして起動でき、専用アイコンが付きます。

- **オフライン**: アプリの外枠（HTML/CSS/JS/アイコン）はキャッシュされ、圏外でも画面は開きます。
  ただしバスの到着情報はリアルタイムのため、表示にはネットワークが必要です
  （古い予測を見せないよう、API応答は意図的にキャッシュしていません）。
- **配信スコープ**: Service Worker は `/sw.js`（ルート配信、スコープ `/`）。`manifest.webmanifest` も
  ルートで配信。アイコンは `/app/icons/`。
- **HTTPS必須**: Service Worker は `https://` か `localhost` でのみ有効です。
  スマホから使うときは、後述のいずれかで **HTTPS** で公開してください
  （Fly.io / Render などは標準でHTTPSが付きます。VPSなら Caddy か nginx + Let's Encrypt）。

アイコンを差し替えたいときは `backend/tools/make_pwa_icons.py` を編集して再生成します。

## 今後の課題
- 接近プッシュ通知（あと◯分／◯駅）、ホーム画面ウィジェット
- 運休Alertの常時表示・ハイライト
- 多事業者対応（`providers.py` に `Provider` を追加）
