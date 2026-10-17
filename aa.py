# -*- coding: utf-8 -*-
"""aa.py —— 纯 Python 抗锯齿栅格化，给 Tk 画布用

Tk 画布画的圆、圆弧、圆角多边形都不做抗锯齿，边缘一圈锯齿，看起来很糙。
这里用有向距离场（SDF）按像素算覆盖率，生成 tk.PhotoImage 贴到画布上。
PhotoImage 不支持半透明，所以每张图都要给出它所在位置的实色背景 bg。
"""

from __future__ import annotations

import math


def rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def hexc(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def blend(fg, bg, a: float) -> tuple:
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


def mix(fg: str, bg: str, a: float) -> str:
    return hexc(blend(rgb(fg), rgb(bg), a))


def cov(sd: float) -> float:
    """有向距离 → 像素覆盖率（1 像素宽的过渡带）。"""
    return 0.0 if sd >= .5 else 1.0 if sd <= -.5 else .5 - sd


# ---- 有向距离函数 --------------------------------------------------------
def sd_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def sd_rrect(px, py, cx, cy, hw, hh, r):
    qx, qy = abs(px - cx) - (hw - r), abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def stroke(sd, w):
    return abs(sd) - w / 2


# ---- 生成像素行 ----------------------------------------------------------
def rrect_rows(w: int, h: int, r: float, fill: str, bg: str,
               border: str | None = None, bw: int = 1) -> list[list[str]]:
    """圆角矩形（可带 1px 描边）。只有四个角逐像素算，直边直接填色，大图也很快。"""
    F, G = rgb(fill), rgb(bg)
    B = rgb(border) if border else None
    fh, bh = hexc(F), hexc(B) if B else None
    rc = min(int(math.ceil(r)) + 1, w // 2, h // 2)

    def px(x, y):
        sd = sd_rrect(x + .5, y + .5, w / 2, h / 2, w / 2, h / 2, r)
        a = cov(sd)
        if not B:
            return hexc(blend(F, G, a))
        col = blend(B, G, a)
        return hexc(blend(F, col, cov(sd + bw)))

    rows = []
    for y in range(h):
        edge_row = B is not None and (y < bw or y >= h - bw)
        row = [bh if edge_row else fh] * w
        if B is not None:
            for x in range(bw):
                row[x] = row[w - 1 - x] = bh
        if y < rc or y >= h - rc:
            for x in list(range(rc)) + list(range(w - rc, w)):
                row[x] = px(x, y)
        rows.append(row)
    return rows


def shape_rows(w: int, h: int, bg: str, layers) -> list[list[str]]:
    """通用：layers = [(颜色, sdf(px, py)), …]，后面的盖在前面上。适合小图（图标、开关）。"""
    G = rgb(bg)
    L = [(rgb(c), f) for c, f in layers]
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            px, py, col = x + .5, y + .5, G
            for c, f in L:
                a = cov(f(px, py))
                if a > 0:
                    col = blend(c, col, a)
            row.append(hexc(col))
        rows.append(row)
    return rows


class Ring:
    """环形进度：预先算好轨道和每个环上像素的角度，每帧只改环上的像素，动画也流畅。"""

    def __init__(self, d: int, lw: float, track: str, bg: str):
        self.d, self.c, self.hw = d, d / 2, lw / 2
        self.rm = d / 2 - .5 - lw / 2              # 环中线半径
        T, G = rgb(track), rgb(bg)
        self.base, self.band = [], []
        for y in range(d):
            row = []
            for x in range(d):
                px, py = x + .5, y + .5
                a = cov(abs(math.hypot(px - self.c, py - self.c) - self.rm) - self.hw)
                col = blend(T, G, a) if a > 0 else G
                if a > 0:
                    ang = (math.atan2(px - self.c, self.c - py) / (2 * math.pi)) % 1.0
                    self.band.append((y, x, px, py, a, ang, col))
                row.append(hexc(col))
            self.base.append(row)

    def rows(self, frac: float, color: str) -> list[list[str]]:
        rows = [list(r) for r in self.base]
        f = max(0.0, min(1.0, frac))
        if f <= 0.003:
            return rows
        C = rgb(color)
        sx, sy = self.c, self.c - self.rm
        ex = self.c + self.rm * math.sin(2 * math.pi * f)
        ey = self.c - self.rm * math.cos(2 * math.pi * f)
        for y, x, px, py, a, ang, base in self.band:
            p = a if ang <= f else 0.0
            if f < 1.0:                                # 两端圆头
                p = max(p, cov(math.hypot(px - sx, py - sy) - self.hw),
                        cov(math.hypot(px - ex, py - ey) - self.hw))
            if p > 0:
                rows[y][x] = hexc(blend(C, base, p))
        return rows


def put(img, rows) -> None:
    img.put(" ".join("{" + " ".join(r) + "}" for r in rows))


def photo(tk, master, rows):
    img = tk.PhotoImage(master=master, width=len(rows[0]), height=len(rows))
    put(img, rows)
    return img
