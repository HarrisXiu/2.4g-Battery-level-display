# -*- coding: utf-8 -*-
"""外设电量监视器 —— Cherry 键盘 / 罗技 · VGN · ATK · 雷柏 鼠标（可扩展）

    python main.py                  打开面板（默认）
    python main.py --tray           托盘常驻（每台设备一个电量数字图标）
    python main.py --once           读一次，打印后退出
    python main.py --list           列出所有 HID 接口（找新设备的 VID/PID/usage page）
    python main.py --sniff 046A:01DB   监听某个设备上报的报文（摸新协议用）
    python main.py --quit           让后台托盘退出
    python main.py --autostart on|off|status
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


CONSOLE_FLAGS = ("--once", "--list", "--sniff", "--autostart", "--quit",
                 "-h", "--help")


def _setup_streams() -> None:
    """打包成无控制台 exe 后 sys.stdout 是 None；命令行子命令要接到父进程的控制台上。"""
    import paths
    if not paths.FROZEN:
        return
    # 只在"没有有效标准输出"（从 cmd 直接敲）时才接控制台；被重定向 / 管道时保持原样
    if sys.stdout is None and any(a in CONSOLE_FLAGS for a in sys.argv[1:]):
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(0xFFFFFFFF):      # 父进程的控制台
            try:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = sys.stdout
            except OSError:
                pass
    for name in ("stdout", "stderr"):                             # 托盘/面板：丢弃输出
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_once(as_json: bool = False) -> int:
    import core
    res = core.scan()
    if as_json:
        import json
        from dataclasses import asdict
        print(json.dumps([asdict(r) for r in res.readings], ensure_ascii=False,
                         indent=2))
        return 0
    for r in res.readings:
        tag = "" if r.verified else "（未实测）"
        if r.ok:
            chg = "，充电中" if r.charging else ""
            print(f"[{r.brand}] {r.name}: {r.level}%{chg}  {tag}")
            print(f"      {r.source}" + (f" · {r.note}" if r.note else ""))
        else:
            print(f"[{r.brand}] {r.name}: 读取失败 —— {r.error} {tag}")
    for e in res.errors:
        print("注意：", e)
    return 0 if any(r.ok for r in res.readings) else 1


def cmd_list() -> int:
    import hidraw
    items = sorted(hidraw.enumerate_interfaces(),
                   key=lambda i: (i.vid, i.pid, i.usage_page, i.usage))
    last = None
    for i in items:
        if i.vid_pid != last:
            last = i.vid_pid
            print(f"\n{i.vid_pid}  {i.manufacturer} {i.product}")
        flag = "  [系统独占]" if i.reserved else ""
        ids = ""
        try:
            with hidraw.HidDevice(i, write=False) as d:
                ids = "  ".join(f"{k}ID " + ",".join(f"{x:02X}" for x in v)
                                for k, v in d.report_ids().items())
        except hidraw.HidError:
            pass
        print(f"   usage {i.usage_page:04X}:{i.usage:04X}  in={i.input_len:<4}"
              f" out={i.output_len:<4} feature={i.feature_len:<5}{flag}"
              + (f"  [{ids}]" if ids else ""))
    return 0


def cmd_sniff(target: str, seconds: float) -> int:
    import hidraw
    vid, pid = (int(x, 16) for x in target.split(":"))
    ifaces = [i for i in hidraw.enumerate_interfaces()
              if i.vid == vid and i.pid == pid and i.input_len and not i.reserved]
    if not ifaces:
        print("没找到可监听的接口（用 --list 确认 VID:PID）")
        return 1
    print(f"监听 {target} 的 {len(ifaces)} 个接口 {seconds:.0f} 秒…"
          "（这时去操作设备 / 打开厂商软件）")
    lock, t0 = threading.Lock(), time.monotonic()
    stop = threading.Event()

    def run(iface):
        last = None
        try:
            dev = hidraw.HidDevice(iface, write=False)
        except hidraw.HidError as e:
            print(f"打不开 {iface.usage_page:04X}: {e}")
            return
        with dev:
            while not stop.is_set():
                r = dev.read(timeout_ms=200)
                if r and r != last:
                    last = r
                    with lock:
                        print(f"{time.monotonic() - t0:7.2f}s  "
                              f"{iface.usage_page:04X}:{iface.usage:04X}  "
                              f"{r.hex(' ')}")

    ts = [threading.Thread(target=run, args=(i,), daemon=True) for i in ifaces]
    for t in ts:
        t.start()
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    stop.set()
    for t in ts:
        t.join(1)
    return 0


def main() -> int:
    _setup_streams()
    _utf8()
    ap = argparse.ArgumentParser(description="外设电量监视器")
    ap.add_argument("--tray", action="store_true", help="托盘常驻")
    ap.add_argument("--once", action="store_true", help="读一次就退出")
    ap.add_argument("--json", action="store_true", help="--once 时输出 JSON")
    ap.add_argument("--list", action="store_true", help="列出所有 HID 接口")
    ap.add_argument("--sniff", metavar="VID:PID", help="监听某设备的上报报文")
    ap.add_argument("--seconds", type=float, default=30, help="--sniff 时长")
    ap.add_argument("--quit", action="store_true", help="让托盘退出")
    ap.add_argument("--autostart", choices=["on", "off", "status"])
    ap.add_argument("--debug", action="store_true", help="托盘前台输出调试信息")
    a = ap.parse_args()

    if a.list:
        return cmd_list()
    if a.sniff:
        return cmd_sniff(a.sniff, a.seconds)
    if a.once:
        return cmd_once(a.json)
    if a.autostart:
        import config
        if a.autostart == "status":
            print("开机自启：", "已启用" if config.autostart_enabled() else "未启用")
        else:
            ok = config.set_autostart(a.autostart == "on")
            print("已" + ("加入" if a.autostart == "on" else "取消") + "开机自启",
                  "" if ok else "（失败）")
        return 0
    if a.quit:
        import tray
        print("已通知托盘退出" if tray.quit_running() else "托盘没在运行")
        return 0
    if a.tray:
        import tray
        return tray.run(debug=a.debug)
    import panel
    return panel.run()


if __name__ == "__main__":
    sys.exit(main())
