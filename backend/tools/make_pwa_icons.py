#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PWA用アイコンを生成する（web/icons/）。

シンプルなバスのアイコンをテーマ色背景に描く。
  - icon-192.png / icon-512.png        … purpose "any"
  - icon-512-maskable.png              … purpose "maskable"（中央80%セーフゾーン）
  - apple-touch-icon-180.png           … iOS ホーム画面用（透過なし）
再生成: python tools/make_pwa_icons.py
"""

import pathlib
from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).resolve().parents[2] / "web" / "icons"

BG = (22, 50, 79)        # #16324f テーマ背景
BODY = (244, 196, 48)    # 車体（黄）
WINDOW = (120, 182, 255) # 窓（水色）
DARK = (15, 23, 32)      # タイヤ・縁


def _rrect(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def draw_bus(size: int, safe: float = 1.0) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)

    # コンテンツ領域（maskable はセーフゾーン内に収める）
    m = size * (1 - safe) / 2
    cx0, cy0 = m, m
    side = size - 2 * m
    # バス車体
    bx0 = cx0 + side * 0.14
    bx1 = cx0 + side * 0.86
    by0 = cy0 + side * 0.22
    by1 = cy0 + side * 0.74
    _rrect(d, [bx0, by0, bx1, by1], r=side * 0.10, fill=BODY)

    # 窓（上段に3つ）
    w = (bx1 - bx0)
    pad = w * 0.10
    win_y0 = by0 + (by1 - by0) * 0.16
    win_y1 = by0 + (by1 - by0) * 0.50
    inner = bx1 - bx0 - 2 * pad
    gap = inner * 0.06
    ww = (inner - 2 * gap) / 3
    for i in range(3):
        x0 = bx0 + pad + i * (ww + gap)
        _rrect(d, [x0, win_y0, x0 + ww, win_y1], r=ww * 0.18, fill=WINDOW)

    # 下部ストライプ
    d.rectangle([bx0, by0 + (by1 - by0) * 0.62, bx1, by0 + (by1 - by0) * 0.70], fill=DARK)

    # タイヤ
    r = side * 0.07
    ty = by1
    for fx in (bx0 + w * 0.24, bx1 - w * 0.24):
        d.ellipse([fx - r, ty - r, fx + r, ty + r], fill=DARK)

    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    draw_bus(192).save(OUT / "icon-192.png")
    draw_bus(512).save(OUT / "icon-512.png")
    draw_bus(512, safe=0.80).save(OUT / "icon-512-maskable.png")
    draw_bus(180).save(OUT / "apple-touch-icon-180.png")
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
