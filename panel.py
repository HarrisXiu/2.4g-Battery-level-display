# -*- coding: utf-8 -*-
"""panel.py —— 面板：圆角 / 圆环 / 开关都是 aa.py 抗锯齿生成的贴图；拖动边框可改大小"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
import traceback

import aa
import config
import core
import paths

BG = "#0c0e12"
CARD, CARD_BORDER, CARD_BORDER_HI = "#171b22", "#232933", "#3b4d72"
SURF, SURF_BORDER = "#13161c", "#20252e"
TRACK, BTN, BTN_HI = "#262c37", "#232934", "#2d3441"
TEXT, MUTED, DIM, AMBER = "#eef1f6", "#8d96a7", "#5f6879", "#f2a65a"
ACCENT, ACCENT_HI, ACCENT_OFF = "#5b8cff", "#7099ff", "#2a3754"
UI = "Microsoft YaHei UI"
KIND_LABEL = {"keyboard": "键盘", "mouse": "鼠标", "headset": "耳机", "other": "设备"}
KIND_ORDER = {"keyboard": 0, "mouse": 1, "headset": 2, "other": 3}
INTERVAL_SHORT = {30: "30 秒", 60: "1 分", 120: "2 分", 300: "5 分", 600: "10 分",
                  1800: "30 分"}

# 版面（逻辑像素，实际会乘 DPI 缩放）
PAD, GAP, CW, CH = 28, 16, 372, 150
FW = CW * 2 + GAP                              # 默认内容区宽度（两列）
MIN_CW = 300                                   # 卡片最窄宽度：再窄就换成少一列
MAX_COLS = 3
MIN_FW = 592                                   # 内容区最窄宽度（设置栏一行要放得下）
SETTINGS_H = 112
RING, RING_LW, BADGE = 96, 10, 46


def level_hex(level) -> str:
    return config.rgb_hex(config.level_rgb(level))


def _glyph_layers(kind: str, D: float, col: str):
    """设备图标（画在直径 D 的圆形徽章里），返回 aa.shape_rows 的图层。"""
    c, lw = D / 2, max(1.6, D * .045)
    st, rr, seg = aa.stroke, aa.sd_rrect, aa.sd_segment
    if kind == "keyboard":
        L = [(col, lambda x, y: st(rr(x, y, c, c, .30 * D, .19 * D, .06 * D), lw))]
        for ky in (-.075, .015):
            for kx in (-.18, -.06, .06, .18):
                L.append((col, lambda x, y, kx=kx, ky=ky:
                          rr(x, y, c + kx * D, c + ky * D, .032 * D, .026 * D, .01 * D)))
        L.append((col, lambda x, y: seg(x, y, c - .1 * D, c + .1 * D,
                                        c + .1 * D, c + .1 * D) - lw / 2))
        return L
    if kind == "mouse":
        return [(col, lambda x, y: st(rr(x, y, c, c, .17 * D, .26 * D, .17 * D), lw)),
                (col, lambda x, y: seg(x, y, c, c - .26 * D, c, c - .07 * D) - lw / 2),
                (col, lambda x, y: seg(x, y, c - .17 * D, c - .07 * D,
                                       c + .17 * D, c - .07 * D) - lw / 2)]
    if kind == "headset":
        cy = c + .03 * D
        return [(col, lambda x, y: max(st(aa.sd_circle(x, y, c, cy, .22 * D), lw), y - cy)),
                (col, lambda x, y: rr(x, y, c - .22 * D, c + .12 * D, .055 * D, .1 * D, .04 * D)),
                (col, lambda x, y: rr(x, y, c + .22 * D, c + .12 * D, .055 * D, .1 * D, .04 * D))]
    return [(col, lambda x, y: st(rr(x, y, c - .03 * D, c, .24 * D, .14 * D, .04 * D), lw)),
            (col, lambda x, y: rr(x, y, c + .25 * D, c, .025 * D, .06 * D, .01 * D)),
            (col, lambda x, y: rr(x, y, c - .1 * D, c, .12 * D, .08 * D, .02 * D))]


def _enable_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _dark_titlebar(root) -> None:
    """Win10 1809+ / Win11：标题栏变深，和面板融为一体。"""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        r, g, b = aa.rgb(BG)
        t = aa.rgb(TEXT)
        for attr, val in ((20, 1), (35, (b << 16) | (g << 8) | r),
                          (36, (t[2] << 16) | (t[1] << 8) | t[0])):
            v = ctypes.c_int(val)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)
    except Exception:
        pass


HEAD_H = 104                                   # 顶栏高度
FOOT_H = SETTINGS_H + PAD - 4                  # 底栏高度（设置区 + 下边距）
THUMB, THUMB_HI = "#323946", "#4a5466"


class Panel:
    """窗口分三块画布：顶栏（固定）/ 卡片区（可滚动）/ 设置栏（贴底）。
    拖动窗口边框时按新宽度重排：列数 1~3 自动切换，卡片跟着变宽变窄。"""

    def __init__(self):
        import tkinter as tk
        from tkinter import font as tkfont
        self.tk = tk
        _enable_dpi()
        self.root = tk.Tk()
        self.root.title(config.PANEL_TITLE)
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        try:
            self.root.iconbitmap(default=paths.resource(os.path.join("assets", "app.ico")))
        except Exception:
            pass
        self.sc = max(1.0, self.root.winfo_fpixels("1i") / 96)
        fams = set(tkfont.families(self.root))
        num = next((f for f in ("Segoe UI Variable Display", "Segoe UI") if f in fams), UI)

        def F(family, size, weight="normal"):
            return tkfont.Font(root=self.root, family=family, size=size, weight=weight)
        self.f_title, self.f_sub = F(UI, 19, "bold"), F(UI, 9)
        self.f_name, self.f_small = F(UI, 12, "bold"), F(UI, 9)
        self.f_word, self.f_body = F(UI, 11, "bold"), F(UI, 10)
        self.f_btn, self.f_seg = F(UI, 10, "bold"), F(UI, 9)
        self.f_num, self.f_pct = F(num, 24, "bold"), F(num, 11)
        self.f_num3 = F(num, 19, "bold")                 # 三位数（100）用小一号，别顶到圆环

        S = self.S
        opts = dict(bg=BG, highlightthickness=0, borderwidth=0)
        self.head = tk.Canvas(self.root, height=S(HEAD_H), **opts)
        self.foot = tk.Canvas(self.root, height=S(FOOT_H), **opts)
        self.body = tk.Canvas(self.root, yscrollincrement=S(24), **opts)
        self.head.pack(side="top", fill="x")
        self.foot.pack(side="bottom", fill="x")
        self.body.pack(side="top", fill="both", expand=True)
        self.cv = self.head                              # 控件函数画到"当前画布"上
        _dark_titlebar(self.root)

        self.cfg = config.load()
        self.state = {"busy": False, "auto": True, "boot": config.autostart_enabled(),
                      "tray": False, "scanned": False}
        self.readings: list = []
        self.updated = ""
        self.cache: dict = {}
        self.used: set = set()
        self.size = (0, 0)               # 上次排版时的窗口尺寸
        self.relayout_job = None
        self.save_job = None
        self.overflow = False            # 卡片区内容是否超出（需要滚动）
        self.visible_h = 0
        self.drag = None
        # 没存过窗口大小时，扫描到设备后自动把窗口拉到刚好放下；用户拖过边框就不再自动改
        self.auto_size = not (self.cfg.get("window") or [])
        self.expect_size = None
        self.rings: dict = {}            # 设备 key -> 环形表状态（贴图 / 当前值 / 目标值 …）
        self.animating = False
        self.timer = None
        self.retry_job = None
        self.results: "queue.Queue" = queue.Queue()

    # ---- 小工具 --------------------------------------------------------
    def S(self, n) -> int:
        return int(round(n * self.sc))

    def img(self, key, make):
        self.used.add(key)
        if key not in self.cache:
            self.cache[key] = aa.photo(self.tk, self.root, make())
        return self.cache[key]

    def rrect(self, w, h, r, fill, bg, border=None):
        return self.img(("rr", w, h, r, fill, bg, border),
                        lambda: aa.rrect_rows(w, h, r, fill, bg, border))

    def hover(self, tag, item=None, normal=None, hot=None, cursor="hand2"):
        cv = self.cv

        def enter(_e):
            if hot is not None:
                cv.itemconfigure(item, image=hot)
            cv.configure(cursor=cursor)

        def leave(_e):
            if hot is not None:
                cv.itemconfigure(item, image=normal)
            cv.configure(cursor="")
        cv.tag_bind(tag, "<Enter>", enter)
        cv.tag_bind(tag, "<Leave>", leave)

    def click(self, tag, fn):
        self.cv.tag_bind(tag, "<Button-1>", lambda _e: fn())

    # ---- 控件 ----------------------------------------------------------
    def button(self, tag, x, y, w, h, text, bg, fn, primary=False, enabled=True):
        S, cv = self.S, self.cv
        W, H = S(w), S(h)
        if primary:
            base, hot = (ACCENT, ACCENT_HI) if enabled else (ACCENT_OFF, ACCENT_OFF)
        else:
            base, hot = BTN, BTN_HI
        n = self.rrect(W, H, S(10), base, bg)
        hh = self.rrect(W, H, S(10), hot, bg)
        item = cv.create_image(x, y, anchor="nw", image=n, tags=(tag,))
        fg = "#ffffff" if primary and enabled else TEXT if enabled else MUTED
        cv.create_text(x + W / 2, y + H / 2, text=text, fill=fg,
                       font=self.f_btn if primary else self.f_body, tags=(tag,))
        if enabled:
            self.hover(tag, item, n, hh)
            self.click(tag, fn)
        else:
            cv.tag_unbind(tag, "<Button-1>")
            self.hover(tag, cursor="")

    def toggle(self, tag, x, y, value, fn):
        S, cv = self.S, self.cv
        W, H = S(44), S(24)
        tc = ACCENT if value else TRACK
        track = self.rrect(W, H, H / 2, tc, SURF)
        d = H - S(6)
        knob = self.img(("knob", d, tc), lambda: aa.shape_rows(
            d, d, tc, [("#ffffff", lambda px, py: aa.sd_circle(px, py, d / 2, d / 2, d / 2 - .5))]))
        cv.create_image(x, y, anchor="nw", image=track, tags=(tag,))
        kx = x + W - S(3) - d if value else x + S(3)
        cv.create_image(kx, y + S(3), anchor="nw", image=knob, tags=(tag,))
        self.hover(tag)
        self.click(tag, lambda: fn(not value))

    def segmented(self, x, y, options, value, fn):
        S, cv = self.S, self.cv
        cw, H = S(54), S(32)
        W = cw * len(options) + S(6)
        cv.create_image(x, y, anchor="nw", image=self.rrect(W, H, S(10), TRACK, SURF))
        sel = self.rrect(cw - S(4), H - S(8), S(8), ACCENT, TRACK)
        for i, (val, label) in enumerate(options):
            tag = f"seg{val}"
            sx = x + S(3) + i * cw
            on = val == value
            if on:
                cv.create_image(sx + S(2), y + S(4), anchor="nw", image=sel)
            # 透明的点击区域，鼠标在字的间隙里也能点中
            cv.create_rectangle(sx, y, sx + cw, y + H, outline="", fill="", tags=(tag,))
            t = cv.create_text(sx + cw / 2, y + H / 2, text=label,
                               fill="#ffffff" if on else MUTED,
                               font=self.f_btn if on else self.f_seg, tags=(tag,))
            if on:
                for seq in ("<Button-1>", "<Enter>", "<Leave>"):
                    cv.tag_unbind(tag, seq)
                continue
            cv.tag_bind(tag, "<Enter>", lambda e, t=t: (
                cv.itemconfigure(t, fill=TEXT), cv.configure(cursor="hand2")))
            cv.tag_bind(tag, "<Leave>", lambda e, t=t: (
                cv.itemconfigure(t, fill=MUTED), cv.configure(cursor="")))
            self.click(tag, lambda v=val: fn(v))
        return W

    def pill(self, x, y, text, color, tags):
        S = self.S
        w, h = self.f_small.measure(text) + S(18), S(22)
        fill = aa.mix(color, CARD, .16)
        self.cv.create_image(x, y, anchor="w", tags=tags,
                             image=self.rrect(w, h, h / 2, fill, CARD))
        self.cv.create_text(x + w / 2, y, text=text, fill=color, font=self.f_small,
                            tags=tags)
        return x + w + S(8)

    # ---- 卡片 ----------------------------------------------------------
    def card(self, i, x, y, W, r):
        S, cv = self.S, self.cv
        H = S(CH)
        tag = f"card{i}"
        n = self.rrect(W, H, S(18), CARD, BG, CARD_BORDER)
        hot = self.rrect(W, H, S(18), CARD, BG, CARD_BORDER_HI)
        bgi = cv.create_image(x, y, anchor="nw", image=n, tags=(tag,))
        self.hover(tag, bgi, n, hot, cursor="")

        ok = r.ok
        col = level_hex(r.level) if ok else MUTED
        # 设备徽章
        D = S(BADGE)
        badge = self.img(("badge", r.kind, col, D), lambda: aa.shape_rows(
            D, D, CARD,
            [(aa.mix(col, CARD, .15),
              lambda px, py: aa.sd_circle(px, py, D / 2, D / 2, D / 2 - .5))]
            + _glyph_layers(r.kind, D, col)))
        cv.create_image(x + S(20), y + S(20), anchor="nw", image=badge, tags=(tag,))
        # 名称 / 品牌
        tx = x + S(20) + D + S(14)
        ring_d = S(RING)
        maxw = W - (tx - x) - ring_d - S(36)
        name = r.name
        if self.f_name.measure(name) > maxw:
            while name and self.f_name.measure(name + "…") > maxw:
                name = name[:-1]
            name += "…"
        cv.create_text(tx, y + S(33), anchor="w", text=name, fill=TEXT,
                       font=self.f_name, tags=(tag,))
        cv.create_text(tx, y + S(56), anchor="w", fill=MUTED, font=self.f_small,
                       text=f"{r.brand} · {KIND_LABEL.get(r.kind, '设备')}", tags=(tag,))

        # 状态词 + 标签
        lx, ly = x + S(20), y + S(98)
        if ok:
            word = ("电量充足" if r.level >= 60 else "电量中等" if r.level >= 30
                    else "电量偏低")
            cv.create_text(lx, ly, anchor="w", text=word, fill=col, font=self.f_word,
                           tags=(tag,))
            lx += self.f_word.measure(word) + S(12)
        if r.charging:
            lx = self.pill(lx, ly, "⚡ 充电中", level_hex(100), (tag,))
        if r.stale:
            lx = self.pill(lx, ly, "休眠中", AMBER, (tag,))
        if not r.verified:
            lx = self.pill(lx, ly, "未实测", AMBER, (tag,))
        # 底部一行
        when = time.strftime("%H:%M", time.localtime(r.ts))
        if r.stale:
            foot, fc = f"显示 {when} 的读数，动一下设备即可刷新", DIM
        elif not ok:
            foot, fc = r.error or "读取失败", AMBER
        else:
            foot, fc = f"{when} 读取", DIM
        cv.create_text(x + S(20), y + S(127), anchor="w", text=foot, fill=fc,
                       font=self.f_small, width=W - ring_d - S(56), tags=(tag,))

        # 环形电量表（动画在 animate() 里推进）
        raster = self.cache.get(("raster", ring_d))
        if raster is None:
            raster = self.cache[("raster", ring_d)] = aa.Ring(ring_d, S(RING_LW), TRACK, CARD)
        ent = self.rings.get(r.key)
        if ent is None:
            ent = self.rings[r.key] = {
                "img": aa.photo(self.tk, self.root, raster.rows(0, col)), "cur": 0.0}
        ent.update(target=float(r.level) if ok else 0.0, col=col, raster=raster, ok=ok,
                   dirty=True, cv=cv)
        rx, ry = x + W - S(22) - ring_d, y + (H - ring_d) / 2
        cv.create_image(rx, ry, anchor="nw", image=ent["img"], tags=(tag,))
        cx, cy = rx + ring_d / 2, ry + ring_d / 2
        label = str(r.level) if ok else "--"
        fnum = self.f_num3 if len(label) >= 3 else self.f_num
        nw, pw = fnum.measure(label), self.f_pct.measure("%") if ok else 0
        right = cx + (nw - pw) / 2 if ok else cx + nw / 2
        ent["item"] = cv.create_text(right, cy, anchor="e",
                                     text=str(int(round(ent["cur"]))) if ok else "--",
                                     fill=TEXT if ok else MUTED, font=fnum, tags=(tag,))
        if ok:
            cv.create_text(right + S(2), cy + S(5), anchor="w", text="%", fill=MUTED,
                           font=self.f_pct, tags=(tag,))

    def animate(self):
        moving = False
        for ent in self.rings.values():
            cur, target = ent["cur"], ent["target"]
            if abs(target - cur) < 0.3:
                cur = target
            else:
                cur += (target - cur) * 0.2
                moving = True
            if cur != ent["cur"] or ent.get("dirty"):
                ent["cur"], ent["dirty"] = cur, False
                aa.put(ent["img"], ent["raster"].rows(cur / 100, ent["col"]))
                if ent["ok"]:
                    ent["cv"].itemconfigure(ent["item"], text=str(int(round(cur))))
        self.animating = moving
        if moving:
            self.root.after(16, self.animate)

    # ---- 版面 ----------------------------------------------------------
    def grid(self, avail: int, n: int) -> tuple[int, int]:
        """按可用宽度决定列数和卡片宽度。"""
        S = self.S
        cols = max(1, min(MAX_COLS, n or 1, (avail + S(GAP)) // (S(MIN_CW) + S(GAP))))
        return cols, (avail - (cols - 1) * S(GAP)) // cols

    def cards_height(self, width: int) -> int:
        """给定窗口宽度时，卡片区内容的总高度。"""
        S = self.S
        full = max(S(MIN_FW), width - 2 * S(PAD))
        cols, _ = self.grid(full, len(self.readings))
        rows = max(1, -(-len(self.readings) // cols))
        return rows * (S(CH) + S(GAP))

    def max_height(self) -> int:
        return self.root.winfo_screenheight() - self.S(80)

    def layout(self):
        S = self.S
        self.used = set()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if width <= 1:                                  # 窗口还没显示出来
            width, height = self.initial_size()
        self.size = (width, height)
        x0 = S(PAD)
        full = max(S(MIN_FW), width - 2 * x0)
        self.draw_head(x0, full)
        self.draw_body(x0, full, width, height)
        self.draw_foot(x0, full)
        # 最小尺寸：设置栏放得下、至少露出一行卡片（更多的卡片可以滚动查看）
        self.root.minsize(S(MIN_FW) + 2 * x0, S(HEAD_H) + S(FOOT_H) + S(CH) + S(GAP))
        for k in [k for k in self.cache if k[0] == "rr" and k not in self.used]:
            del self.cache[k]                           # 旧尺寸的圆角图不再需要
        if not self.animating:
            self.animating = True
            self.root.after(16, self.animate)

    def draw_head(self, x0, full):
        S = self.S
        cv = self.cv = self.head
        cv.delete("all")
        cv.create_text(x0, S(44), anchor="w", text=config.PANEL_TITLE, fill=TEXT,
                       font=self.f_title)
        if not self.state["scanned"]:
            sub = "正在扫描设备…"
        else:
            n = len(self.readings)
            sub = (f"{n} 台设备 · " if n else "") + f"{self.updated} 更新"
            if not self.state["auto"]:
                sub += " · 自动刷新已关闭"
        cv.create_text(x0, S(72), anchor="w", text=sub, fill=MUTED, font=self.f_sub)
        busy = self.state["busy"]
        self.button("refresh", x0 + full - S(124), S(30), 124, 38,
                    "读取中…" if busy else "↻  立即刷新", BG, self.refresh,
                    primary=True, enabled=not busy)

    def draw_body(self, x0, full, width, height):
        S = self.S
        cv = self.cv = self.body
        first = cv.yview()[0] if self.overflow else 0.0   # 重排后保持滚动位置
        cv.delete("all")
        rs = self.readings
        cols, cw = self.grid(full, len(rs))
        if not rs:
            cv.create_image(x0, 0, anchor="nw",
                            image=self.rrect(full, S(CH), S(18), BG, BG, CARD_BORDER))
            mid = S(CH) / 2
            if self.state["scanned"]:
                cv.create_text(x0 + full / 2, mid - S(12), text="没有检测到设备",
                               fill=TEXT, font=self.f_word)
                cv.create_text(x0 + full / 2, mid + S(14), fill=DIM,
                               text="插上 2.4G 接收器后会自动出现", font=self.f_small)
            else:
                cv.create_text(x0 + full / 2, mid, text="正在扫描设备…",
                               fill=MUTED, font=self.f_body)
        for i, r in enumerate(rs):
            self.card(i, x0 + (i % cols) * (cw + S(GAP)),
                      (i // cols) * (S(CH) + S(GAP)), cw, r)
        alive = {r.key for r in rs}
        for k in [k for k in self.rings if k not in alive]:
            del self.rings[k]

        content = self.cards_height(width)
        self.visible_h = max(1, height - S(HEAD_H) - S(FOOT_H))
        self.overflow = content > self.visible_h + 1
        cv.configure(scrollregion=(0, 0, width, max(content, self.visible_h)))
        cv.yview_moveto(first if self.overflow else 0.0)
        self.draw_thumb()

    def draw_foot(self, x0, full):
        S = self.S
        cv = self.cv = self.foot
        cv.delete("all")
        sh = S(SETTINGS_H)
        cv.create_image(x0, 0, anchor="nw",
                        image=self.rrect(full, sh, S(16), SURF, BG, SURF_BORDER))
        r1, r2 = S(32), S(84)
        cv.create_text(x0 + S(20), r1, anchor="w", text="刷新间隔", fill=TEXT,
                       font=self.f_body)
        self.segmented(x0 + S(98), r1 - S(16),
                       [(s, INTERVAL_SHORT[s]) for s, _ in config.INTERVALS],
                       self.cfg["interval"], self.on_interval)
        tw = S(44)
        self.toggle("tg_auto", x0 + full - S(20) - tw, r1 - S(12), self.state["auto"],
                    self.on_auto)
        cv.create_text(x0 + full - S(32) - tw, r1, anchor="e", text="自动刷新",
                       fill=TEXT, font=self.f_body)
        cv.create_line(x0 + S(20), S(58), x0 + full - S(20), S(58), fill=SURF_BORDER)
        self.toggle("tg_boot", x0 + S(20), r2 - S(12), self.state["boot"], self.on_boot)
        lab = "开机自启"
        cv.create_text(x0 + S(20) + tw + S(12), r2, anchor="w", text=lab, fill=TEXT,
                       font=self.f_body)
        cv.create_text(x0 + S(20) + tw + S(24) + self.f_body.measure(lab), r2,
                       anchor="w", text="任务管理器「启动」可见", fill=DIM,
                       font=self.f_small)
        self.button("tray", x0 + full - S(20) - S(108), r2 - S(17), 108, 34,
                    "退出托盘" if self.state["tray"] else "启动托盘", SURF,
                    self.on_tray)

    # ---- 滚动 ----------------------------------------------------------
    def draw_thumb(self, hot=False):
        """卡片区右侧的细滚动条（只在内容放不下时出现），可拖动。"""
        S, cv = self.S, self.body
        cv.delete("thumb")
        if not self.overflow:
            return
        top, bot = cv.yview()
        track = self.visible_h - S(GAP)
        oy = cv.canvasy(0)
        x = self.size[0] - S(PAD) / 2
        cv.create_line(x, oy + top * track + S(4), x, oy + bot * track - S(4),
                       width=S(6), capstyle="round", fill=THUMB_HI if hot else THUMB,
                       tags=("thumb",))
        cv.tag_bind("thumb", "<Enter>", lambda e: self.draw_thumb(True))
        cv.tag_bind("thumb", "<Leave>", lambda e: self.drag or self.draw_thumb(False))
        cv.tag_bind("thumb", "<Button-1>", lambda e: setattr(
            self, "drag", (e.y, cv.yview()[0])))
        cv.tag_bind("thumb", "<B1-Motion>", self.on_thumb_drag)
        cv.tag_bind("thumb", "<ButtonRelease-1>", lambda e: (
            setattr(self, "drag", None), self.draw_thumb(False)))

    def on_thumb_drag(self, e):
        if not self.drag:
            return
        y0, top0 = self.drag
        self.body.yview_moveto(top0 + (e.y - y0) / max(1, self.visible_h - self.S(GAP)))
        self.draw_thumb(True)

    def on_wheel(self, e):
        if self.overflow:
            self.body.yview_scroll(int(-e.delta / 120) * 2, "units")
            self.draw_thumb()

    # ---- 窗口大小 ------------------------------------------------------
    def initial_size(self) -> tuple[int, int]:
        """上次的窗口大小（按逻辑像素存盘）；没有就用默认两列、一行卡片的大小。"""
        S = self.S
        saved = self.cfg.get("window") or []
        if len(saved) == 2:
            w, h = S(saved[0]), S(saved[1])
        else:
            w, h = S(FW + 2 * PAD), S(HEAD_H) + S(FOOT_H) + S(CH) + S(GAP)
        w = min(max(w, S(MIN_FW + 2 * PAD)), self.root.winfo_screenwidth())
        return w, min(max(h, S(HEAD_H + FOOT_H + CH + GAP)), self.max_height())

    def fit_height(self):
        """没被用户调过大小时：窗口高度刚好放下所有卡片（不超过屏幕）。"""
        if not self.auto_size:
            return
        w = self.root.winfo_width()
        want = min(self.S(HEAD_H) + self.S(FOOT_H) + self.cards_height(w),
                   self.max_height())
        if want != self.root.winfo_height():
            self.expect_size = (w, want)
            self.root.geometry(f"{w}x{want}")

    def on_resize(self, e):
        if e.widget is not self.root:
            return
        size = (self.root.winfo_width(), self.root.winfo_height())
        if size == self.size:
            return
        if size != self.expect_size:                    # 用户拖了边框 / 最大化
            self.auto_size = False
            if self.save_job:
                self.root.after_cancel(self.save_job)
            self.save_job = self.root.after(800, self.save_size)
        # 拖动边框时事件很密，停顿一下再重排，拖起来不卡
        if self.relayout_job:
            self.root.after_cancel(self.relayout_job)
        self.relayout_job = self.root.after(30, self.layout)

    def save_size(self):
        self.save_job = None
        w, h = self.size
        self.cfg["window"] = [round(w / self.sc), round(h / self.sc)]
        config.save(self.cfg)

    # ---- 事件 ----------------------------------------------------------
    def on_interval(self, v):
        self.cfg["interval"] = v
        config.save(self.cfg)
        self.reschedule()
        self.layout()
        self.refresh()

    def on_auto(self, v):
        self.state["auto"] = v
        self.reschedule()
        self.layout()

    def on_boot(self, v):
        ok = config.set_autostart(v)
        self.state["boot"] = v if ok else config.autostart_enabled()
        self.layout()

    def on_tray(self):
        import tray
        if tray.is_running():
            tray.quit_running()
        else:
            tray.start_detached()
        self.root.after(1500, self.sync_tray)

    def sync_tray(self):
        import tray
        running = tray.is_running()
        if running != self.state["tray"]:
            self.state["tray"] = running
            self.layout()

    # ---- 刷新 ----------------------------------------------------------
    def worker(self):
        try:
            self.results.put(core.scan())
        except Exception:
            traceback.print_exc()
            self.results.put(core.ScanResult(errors=["扫描异常"]))

    def refresh(self):
        if self.state["busy"]:
            return
        self.state["busy"] = True
        self.layout()
        threading.Thread(target=self.worker, daemon=True).start()

    def apply(self, res):
        self.readings = sorted(config.visible(res.readings, self.cfg),
                               key=lambda r: (KIND_ORDER.get(r.kind, 9), r.name))
        self.updated = time.strftime("%H:%M:%S")
        self.state["busy"] = False
        self.state["scanned"] = True
        self.fit_height()
        self.layout()
        if self.retry_job:
            self.root.after_cancel(self.retry_job)
            self.retry_job = None
        if any(not r.ok for r in self.readings):
            # 有设备还没读到（比如雷柏鼠标要等它主动上报）：10 秒后补刷一次，不用等满一个周期
            self.retry_job = self.root.after(10_000, self.refresh)

    def reschedule(self):
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.state["auto"]:
            self.timer = self.root.after(self.cfg["interval"] * 1000, self.tick)

    def tick(self):
        self.refresh()
        self.reschedule()

    def pump(self):                  # 后台线程只往队列放，界面更新都在主线程
        try:
            while True:
                self.apply(self.results.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
            self.state["busy"] = False
        self.root.after(150, self.pump)

    def start(self) -> None:
        """设好窗口大小和事件，画第一帧（run() 和测试脚本共用）。"""
        w, h = self.initial_size()
        self.expect_size = (w, h)
        self.root.geometry(f"{w}x{h}")
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind_all("<MouseWheel>", self.on_wheel)
        try:
            import tray
            self.state["tray"] = tray.is_running()
        except Exception:
            pass
        self.layout()

    def run(self) -> int:
        self.start()
        self.root.after(100, self.refresh)
        self.root.after(150, self.pump)
        self.reschedule()

        def tray_loop():
            self.sync_tray()
            self.root.after(2000, tray_loop)
        self.root.after(2000, tray_loop)
        self.root.mainloop()
        return 0


def run() -> int:
    return Panel().run()
