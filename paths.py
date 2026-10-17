# -*- coding: utf-8 -*-
"""paths.py —— 程序根目录与"怎么再启动自己"。

脚本运行：根目录 = 项目目录，再启动 = pythonw main.py …
打包成 exe（PyInstaller onefile）：__file__ 指向每次启动的临时解压目录，
所以根目录必须取 exe 所在目录——config.json / devices.json / plugins/ 都放在 exe 旁边，
这样整个文件夹拷到哪都能用（便携）。
"""

from __future__ import annotations

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
        else os.path.dirname(os.path.abspath(__file__)))


def launch_cmd(args: list[str]) -> list[str]:
    """再启动自己（面板 / 托盘）用的命令行。"""
    if FROZEN:
        return [sys.executable, *args]
    exe = sys.executable or "python"
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return [pyw if os.path.exists(pyw) else exe,
            os.path.join(ROOT, "main.py"), *args]


def spawn_env() -> dict:
    """onefile 子进程必须自己重新解压，不能复用父进程的临时目录（父进程退出会删掉它）。"""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def resource(rel: str) -> str:
    """打包进 exe 的只读资源（图标等）；脚本运行时就是项目目录里的文件。"""
    base = getattr(sys, "_MEIPASS", ROOT) if FROZEN else ROOT
    return os.path.join(base, rel)
