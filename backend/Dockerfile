# 芸陽バス 接近情報 バックエンド（API + 常時起動のRT集約ポーラ）
# Fly.io / Render / Railway / 任意のコンテナホストで動く。
# ビルドは backend/ をコンテキストに:  docker build -t geiyo-bus ./backend
#
# フロント(PWA)はVercelに分離する構成のため、この像はAPIのみ。
# （web/ を同梱しないので main.py はフロント配信をスキップする。CORSは全許可済み）
FROM python:3.11-slim

WORKDIR /srv

# 依存だけ先に入れてレイヤキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# このバックエンドは状態を持たない（お気に入りはクライアント側localStorage）。
# RTは15秒更新。ポーラは内部で15秒間隔を厳守する。
ENV ENABLE_POLLER=1

EXPOSE 8000
# $PORT が来ればそれを使う（Render/Railway 等）。無ければ 8000。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
