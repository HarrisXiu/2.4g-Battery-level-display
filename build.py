# -*- coding: utf-8 -*-
"""build.py —— 打包成便携 exe：  python build.py

产物在 release/：
    外设电量.exe      单文件，双击即用（面板）；带 --tray 常驻托盘
    devices.json      声明式加设备（可选，exe 旁边的这份会被读取）
    plugins/          Python 插件目录（可选）
只需要 PyInstaller（打包时用，运行时不需要 Python）：pip install pyinstaller
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "外设电量"
ICON = os.path.join(ROOT, "assets", "app.ico")


# ---- 图标：深色圆角底 + 电池 + 绿色电量，纯 Python 画 -----------------------
def _sd_rrect(px, py, cx, cy, hw, hh, r):
    qx, qy = abs(px - cx) - (hw - r), abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def _draw(size: int) -> bytes:
    ss = 3 if size >= 32 else 4
    LIGHT, GREEN, TILE = (232, 235, 241), (74, 222, 128), (26, 30, 38)
    px = bytearray()
    for y in range(size):
        for x in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    u, v = (x + (sx + .5) / ss) / size, (y + (sy + .5) / ss) / size
                    col = None
                    if _sd_rrect(u, v, .5, .5, .5, .5, .22) <= 0:
                        col = TILE
                        if abs(_sd_rrect(u, v, .46, .5, .31, .2, .07)) <= .026:
                            col = LIGHT
                        if _sd_rrect(u, v, .815, .5, .04, .075, .02) <= 0:
                            col = LIGHT
                        if _sd_rrect(u, v, .36, .5, .2, .115, .03) <= 0:
                            col = GREEN
                    if col:
                        acc[0] += col[0]; acc[1] += col[1]; acc[2] += col[2]; acc[3] += 1
            n = ss * ss
            if acc[3]:
                px += bytes((round(acc[2] / acc[3]), round(acc[1] / acc[3]),
                             round(acc[0] / acc[3]), round(255 * acc[3] / n)))
            else:
                px += bytes(4)
    return bytes(px)


def _png(size: int, bgra: bytes) -> bytes:
    rows = b"".join(b"\x00" + b"".join(bytes((bgra[i + 2], bgra[i + 1], bgra[i], bgra[i + 3]))
                    for i in range(y * size * 4, (y + 1) * size * 4, 4))
                    for y in range(size))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def make_icon(path: str) -> None:
    sizes = (16, 24, 32, 48, 64, 128, 256)
    pngs = [_png(s, _draw(s)) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset, entries = 6 + 16 * len(sizes), b""
    for s, data in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(head + entries + b"".join(pngs))


def main() -> int:
    if not os.path.exists(ICON):
        print("生成图标…")
        make_icon(ICON)
    work = tempfile.mkdtemp(prefix="bm_build_")
    release = os.path.join(ROOT, "release")
    exe = os.path.join(release, NAME + ".exe")
    old = os.path.join(release, NAME + ".old.exe")
    for f in (old, exe):
        try:
            if os.path.exists(f):
                os.remove(f)
        except PermissionError:
            if f == exe:
                # 旧版正在运行（托盘 / 面板）：Windows 不让覆盖，但允许改名
                os.replace(exe, old)
                print(f"旧版正在运行，已改名为 {os.path.basename(old)}；重开程序即用新版，旧文件下次打包时自动清理")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--windowed", "--name", NAME, "--icon", ICON,
           "--paths", ROOT, "--add-data", ICON + os.pathsep + "assets", "--collect-submodules", "drivers",
           "--distpath", release, "--workpath", os.path.join(work, "work"),
           "--specpath", work, os.path.join(ROOT, "main.py")]
    print(" ".join(cmd))
    if subprocess.call(cmd, cwd=ROOT) != 0:
        return 1
    shutil.copy(os.path.join(ROOT, "devices.json"), release)
    shutil.copytree(os.path.join(ROOT, "plugins"), os.path.join(release, "plugins"),
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "zz_*"))
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n完成：{exe}  ({os.path.getsize(exe) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
