# -*- coding: utf-8 -*-
"""config.py —— 配置、开机自启、面板/托盘共用的小工具"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from paths import ROOT, launch_cmd

CONFIG_PATH = os.path.join(ROOT, "config.json")
PANEL_TITLE = "外设电量"

DEFAULTS = {
    "interval": 60,        # 刷新间隔（秒）
    "hidden": [],          # 不显示的设备 key，如 ["046D:C54D#1"]
    "names": {},           # 自定义显示名 {key: 名字}
    "window": [],          # 面板窗口大小 [宽, 高]（逻辑像素），拖动边框后自动记住
}
INTERVALS = [(30, "30 秒"), (60, "1 分钟"), (120, "2 分钟"), (300, "5 分钟"),
             (600, "10 分钟"), (1800, "30 分钟")]


def load() -> dict:
    cfg = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in DEFAULTS.items()}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in DEFAULTS:
            if k in data and type(data[k]) is type(DEFAULTS[k]):
                cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}, f,
                      ensure_ascii=False, indent=2)
    except OSError:
        pass


def visible(readings, cfg: dict):
    """按配置过滤隐藏设备并套用自定义名。"""
    for r in readings:
        if r.key in cfg["hidden"]:
            continue
        if r.key in cfg["names"]:
            r.name = cfg["names"][r.key]
        yield r


# ---- 电量颜色：≥60 绿 / 30-59 黄 / <30 红 ----------------------------------
GREY = (139, 147, 161)
_LEVELS = [(60, (74, 222, 128)), (30, (250, 204, 21)), (0, (248, 113, 113))]


def level_rgb(level) -> tuple:
    if level is None:
        return GREY
    for threshold, rgb in _LEVELS:
        if level >= threshold:
            return rgb
    return _LEVELS[-1][1]


def rgb_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


# ---- 开机自启：启动文件夹里的快捷方式，任务管理器「启动」标签可见 ------------
STARTUP_LNK = "外设电量.lnk"


def startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup")


def _lnk_path() -> str:
    return os.path.join(startup_dir(), STARTUP_LNK)


def autostart_enabled() -> bool:
    return os.path.exists(_lnk_path())


def set_autostart(on: bool) -> bool:
    """只响应用户的明确操作；程序自己绝不"纠正"这个设置。"""
    lnk = _lnk_path()
    if not on:
        try:
            if os.path.exists(lnk):
                os.remove(lnk)
            return True
        except OSError:
            return False

    def q(s: str) -> str:
        return s.replace("'", "''")

    cmd = launch_cmd(["--tray"])
    args = " ".join('"%s"' % c if " " in c else c for c in cmd[1:])
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
          "$s.TargetPath='%s';$s.Arguments='%s';"
          "$s.WorkingDirectory='%s';$s.WindowStyle=7;"
          "$s.Description='外设电量托盘';$s.Save()"
          % (q(lnk), q(cmd[0]), q(args), q(ROOT)))
    try:
        os.makedirs(startup_dir(), exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps], check=True, timeout=30,
                       creationflags=0x08000000)       # CREATE_NO_WINDOW
        return os.path.exists(lnk)
    except Exception:
        return False
