# -*- coding: utf-8 -*-
"""tray.py —— 托盘常驻：每台设备一个"电量数字"图标（纯 ctypes）

* 图标内容就是电量数字，颜色 ≥60 绿 / 30-59 黄 / <30 红 / 没读到 灰 "--"
* 左键 = 立刻刷新；双击 / 右键菜单「打开面板」= 打开面板；悬停 = 设备名 + 电量 + 时间
* SetTimer 驱动刷新（间隔来自 config.json，面板里改了下一轮自动生效），读取在后台线程
* 设备增减时图标跟着增减（接收器拔了，对应图标就消失）
* 不写日志；--debug 才往控制台打印
"""

from __future__ import annotations

import ctypes
import subprocess
import threading
import time
import traceback
from ctypes import wintypes
from typing import Optional

import config
import core
import paths
from hidraw import GUID
from drivers import Reading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WND_CLASS = "BatteryMonitorTrayWnd"
MUTEX_NAME = "Local\\BatteryMonitorTray_single_instance"

WM_DESTROY, WM_CLOSE, WM_NULL, WM_TIMER = 0x0002, 0x0010, 0x0000, 0x0113
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_APP = 0x8000
MSG_TRAY, MSG_DONE = WM_APP + 1, WM_APP + 2
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_CHECKED, MF_SEPARATOR = 0, 8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 2, 0x100
SM_CXSMICON, SW_RESTORE = 49, 9
CMD_PANEL, CMD_REFRESH, CMD_BOOT, CMD_QUIT = 1, 2, 3, 4
MAX_ICONS = 8
RETRY_TIMER, RETRY_MS = 2, 10_000

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", ctypes.c_void_p)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", ctypes.c_void_p),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                ("hBalloonIcon", ctypes.c_void_p)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", ctypes.c_void_p),
                ("hbmColor", ctypes.c_void_p)]


class MSG(ctypes.Structure):
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


_V = ctypes.c_void_p
user32.RegisterClassExW.restype = wintypes.WORD
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = _V
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.DWORD] + \
    [ctypes.c_int] * 4 + [_V] * 4
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [_V, wintypes.UINT, ctypes.c_size_t,
                                  ctypes.c_ssize_t]
user32.DestroyWindow.argtypes = [_V]
user32.FindWindowW.restype = _V
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [_V, wintypes.UINT, ctypes.c_size_t,
                                ctypes.c_ssize_t]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [_V, ctypes.c_size_t, wintypes.UINT, _V]
user32.KillTimer.argtypes = [_V, ctypes.c_size_t]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), _V, wintypes.UINT,
                               wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.CreatePopupMenu.restype = _V
user32.AppendMenuW.argtypes = [_V, wintypes.UINT, ctypes.c_size_t,
                               wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [_V, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, _V, _V]
user32.DestroyMenu.argtypes = [_V]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [_V]
user32.ShowWindow.argtypes = [_V, ctypes.c_int]
user32.CreateIconIndirect.restype = _V
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.argtypes = [_V]
gdi32.CreateBitmap.restype = _V
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                               wintypes.UINT, _V]
gdi32.DeleteObject.argtypes = [_V]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = _V
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = _V
kernel32.CreateMutexW.argtypes = [_V, wintypes.BOOL, wintypes.LPCWSTR]


# --------------------------------------------------------------------------
# 数字图标：3x5 点阵字 → BGRA 位图 → HICON
# --------------------------------------------------------------------------
FONT = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001001001001", "8": "111101111101111",
    "9": "111101111001111", "-": "000000111000000",
}


# 托盘配色跟随任务栏主题：浅色任务栏用深一档的颜色，深色任务栏用亮色（都不描边，干净）
PALETTE = {
    "dark":  {"levels": [(60, (74, 222, 128)), (30, (250, 204, 21)), (0, (248, 113, 113))],
              "none": (139, 147, 161), "glyph": (222, 226, 233)},
    "light": {"levels": [(60, (21, 150, 70)), (30, (196, 128, 0)), (0, (214, 40, 40))],
              "none": (110, 118, 130), "glyph": (60, 66, 76)},
}


def taskbar_theme() -> str:
    """读注册表 SystemUsesLightTheme（任务栏 / 通知区跟随它）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                            r"\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] else "dark"
    except OSError:
        return "dark"


def theme_rgb(level, theme: str) -> tuple:
    pal = PALETTE[theme]
    if level is None:
        return pal["none"]
    return next(rgb for t, rgb in pal["levels"] if level >= t)


def _glyph(kind: str, size: int, gh: int) -> set:
    """底部一条高 gh 像素的设备小图标：键盘 = 扁宽带点阵的框，鼠标 = 窄高圆角框带中缝。"""
    y0, pts = size - gh, set()

    def box(x1, y1, x2, y2, round_=False):
        for x in range(x1, x2 + 1):
            for y in (y1, y2):
                pts.add((x, y))
        for y in range(y1, y2 + 1):
            for x in (x1, x2):
                pts.add((x, y))
        if round_:
            pts.difference_update({(x1, y1), (x2, y1), (x1, y2), (x2, y2)})

    if kind == "keyboard":
        x1, x2 = 1, size - 2
        box(x1, y0, x2, size - 1, round_=True)
        dot_rows = [y0 + 2] if gh < 7 else [y0 + 2, y0 + 4]
        for y in dot_rows:
            for x in range(x1 + 2, x2 - 1, 2):
                pts.add((x, y))
        if gh >= 8:                                           # 空格键
            for x in range(x1 + (x2 - x1) // 3, x2 - (x2 - x1) // 3 + 1):
                pts.add((x, size - 3))
    elif kind == "mouse":
        mw = max(5, (gh * 2) // 3) | 1                        # 奇数宽，中缝居中
        x1 = (size - mw) // 2
        box(x1, y0, x1 + mw - 1, size - 1, round_=True)
        for y in range(y0, y0 + max(2, gh // 2)):
            pts.add((x1 + mw // 2, y))
    elif kind == "headset":
        w = gh + 2
        x1 = (size - w) // 2
        for x in range(x1 + 1, x1 + w - 1):
            pts.add((x, y0))
        for y in range(y0 + 1, size):
            pts.update({(x1, y), (x1 + w - 1, y)})
        for y in range(size - 2, size):
            pts.update({(x1 + 1, y), (x1 + w - 2, y)})
    else:                                                     # 电池
        w = min(size - 3, gh * 2)
        x1 = (size - w) // 2
        box(x1, y0, x1 + w - 1, size - 1)
        for y in range(y0 + gh // 3, size - gh // 3):
            pts.add((x1 + w, y))
    return pts


def render_pixels(text: str, rgb: tuple, size: int, kind: str = "",
                  glyph_rgb: tuple = (222, 226, 233)) -> bytearray:
    """size×size 的 BGRA 像素：上面是电量数字，下面是设备类型小图标（区分是哪台设备）。

    透明底；kind 为空时只画数字（居中）。
    """
    n = len(text)
    gap = 1 if size < 24 else 2
    gh = max(5, round(size * 0.34)) if kind else 0
    area = size - gh - (1 if kind else 0)                     # 数字可用高度
    k = max(1, min((size - (n - 1) * gap) // (3 * n), area // 5))
    w, h = 3 * k * n + (n - 1) * gap, 5 * k
    x0, y0 = (size - w) // 2, max(0, (area - h) // 2)
    ink = set()
    for ci, ch in enumerate(text):
        bits = FONT.get(ch, FONT["-"])
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    for dy in range(k):
                        for dx in range(k):
                            ink.add((x0 + ci * (3 * k + gap) + c * k + dx,
                                     y0 + r * k + dy))
    glyph = _glyph(kind, size, gh) if kind else set()

    px = bytearray(size * size * 4)
    for pts, color in ((glyph, glyph_rgb), (ink, rgb)):
        for x, y in pts:
            if 0 <= x < size and 0 <= y < size:
                o = (y * size + x) * 4
                px[o:o + 4] = bytes((color[2], color[1], color[0], 255))
    return px


def render_icon(text: str, rgb: tuple, size: int, kind: str = "",
                glyph_rgb: tuple = (222, 226, 233)):
    px = render_pixels(text, rgb, size, kind, glyph_rgb)
    buf = (ctypes.c_ubyte * len(px)).from_buffer(px)
    color_bmp = gdi32.CreateBitmap(size, size, 1, 32, buf)
    mask = (ctypes.c_ubyte * (((size + 15) // 16) * 2 * size))()
    mask_bmp = gdi32.CreateBitmap(size, size, 1, 1, mask)
    info = ICONINFO(True, 0, 0, mask_bmp, color_bmp)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(color_bmp)
    gdi32.DeleteObject(mask_bmp)
    return hicon


# --------------------------------------------------------------------------
# 进程级工具（面板 / main.py 也会调）
# --------------------------------------------------------------------------
def _tray_hwnd():
    return user32.FindWindowW(WND_CLASS, None)


def is_running() -> bool:
    return bool(_tray_hwnd())


def quit_running() -> bool:
    h = _tray_hwnd()
    return bool(h and user32.PostMessageW(h, WM_CLOSE, 0, 0))


def _spawn(args: list[str]) -> None:
    subprocess.Popen(paths.launch_cmd(args), cwd=paths.ROOT,
                     env=paths.spawn_env(), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)   # DETACHED | NEW_GROUP


def start_detached() -> None:
    _spawn(["--tray"])


def open_panel() -> None:
    h = user32.FindWindowW(None, config.PANEL_TITLE)
    if h:
        user32.ShowWindow(h, SW_RESTORE)
        user32.SetForegroundWindow(h)
    else:
        _spawn([])


# --------------------------------------------------------------------------
# 托盘程序
# --------------------------------------------------------------------------
class Tray:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.cfg = config.load()
        self.hwnd = None
        self.proc_ref = None
        self.busy = False
        self.result: Optional[core.ScanResult] = None
        self.uids: dict[str, int] = {}          # 设备 key -> 图标 uID（稳定不变）
        self.hicons: dict[int, int] = {}        # uID -> 当前 HICON
        self.next_uid = 100
        self.msg_taskbar = user32.RegisterWindowMessageW("TaskbarCreated")
        self.icon_size = user32.GetSystemMetrics(SM_CXSMICON) or 16

    def log(self, msg: str) -> None:
        if self.debug:
            print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

    # ---- 图标 ----------------------------------------------------------
    def _nid(self, uid: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = MSG_TRAY
        return nid

    def _show(self, uid: int, r: Reading) -> None:
        text = str(r.level) if r.ok else "--"
        theme = taskbar_theme()
        hicon = render_icon(text, theme_rgb(r.level, theme), self.icon_size,
                            r.kind if r.key != "__none__" else "",
                            PALETTE[theme]["glyph"])
        nid = self._nid(uid)
        nid.hIcon = hicon
        if r.ok:
            tip = (f"{r.name}：{r.level}%" + ("（充电中）" if r.charging else "")
                   + ("（休眠，旧读数）" if r.stale else "")
                   + f"  {time.strftime('%H:%M', time.localtime(r.ts))}")
        else:
            tip = f"{r.name}：{r.error or '未知'}"
        nid.szTip = tip[:127]
        action = NIM_MODIFY if uid in self.hicons else NIM_ADD
        ok = shell32.Shell_NotifyIconW(action, ctypes.byref(nid))
        if not ok and action == NIM_MODIFY:       # 图标被系统丢了，重新加
            ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        old = self.hicons.get(uid)
        if ok:
            self.hicons[uid] = hicon
            if old:
                user32.DestroyIcon(old)
        else:
            user32.DestroyIcon(hicon)
        self.log(f"{'ADD' if action == NIM_ADD else 'MOD'} {r.name} {text} -> {bool(ok)}")

    def _delete(self, uid: int) -> None:
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(uid)))
        h = self.hicons.pop(uid, None)
        if h:
            user32.DestroyIcon(h)

    def update_icons(self) -> None:
        res = self.result
        order = {"keyboard": 0, "mouse": 1, "headset": 2}
        readings = sorted(config.visible(res.readings, self.cfg),
                          key=lambda r: (order.get(r.kind, 9), r.key)
                          )[:MAX_ICONS] if res else []
        if not readings:
            msg = "正在读取…" if res is None else "没有读到设备"
            readings = [Reading(key="__none__", name="外设电量", brand="",
                                error=msg)]
        keep = set()
        for r in readings:
            uid = self.uids.setdefault(r.key, self._alloc())
            keep.add(r.key)
            self._show(uid, r)
        for key in [k for k in self.uids if k not in keep]:
            self._delete(self.uids.pop(key))

    def _alloc(self) -> int:
        self.next_uid += 1
        return self.next_uid

    def remove_icons(self) -> None:
        for uid in list(self.hicons):
            self._delete(uid)

    # ---- 刷新 ----------------------------------------------------------
    def apply_timer(self) -> None:
        user32.KillTimer(self.hwnd, 1)
        user32.SetTimer(self.hwnd, 1, int(self.cfg["interval"]) * 1000, None)

    def refresh_now(self) -> None:
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._worker, args=(self.hwnd,),
                         daemon=True).start()

    def _worker(self, hwnd) -> None:
        try:
            self.result = core.scan()
        except Exception:
            self.log(traceback.format_exc())
        user32.PostMessageW(hwnd, MSG_DONE, 0, 0)

    def on_timer(self) -> None:
        new = config.load()                   # 面板里改过间隔 / 隐藏设备，这里顺手同步
        changed = new["interval"] != self.cfg["interval"]
        self.cfg = new
        if changed:
            self.apply_timer()
        self.refresh_now()

    # ---- 菜单 ----------------------------------------------------------
    def show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_PANEL, "打开面板")
        user32.AppendMenuW(menu, MF_STRING, CMD_REFRESH, "立即刷新")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if
                           config.autostart_enabled() else 0), CMD_BOOT, "开机自启")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, "退出")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)          # 否则菜单点别处不会收起
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == CMD_PANEL:
            open_panel()
        elif cmd == CMD_REFRESH:
            self.refresh_now()
        elif cmd == CMD_BOOT:
            config.set_autostart(not config.autostart_enabled())
        elif cmd == CMD_QUIT:
            user32.DestroyWindow(self.hwnd)

    # ---- 窗口过程 ------------------------------------------------------
    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == MSG_TRAY:
            ev = int(lparam) & 0xFFFF
            if ev == WM_RBUTTONUP:
                self.show_menu()
            elif ev == WM_LBUTTONUP:
                self.refresh_now()
            elif ev == WM_LBUTTONDBLCLK:
                open_panel()
            return 0
        if msg == MSG_DONE:
            self.busy = False
            self.update_icons()
            res = self.result
            if res and any(not r.ok for r in res.readings):
                # 有设备还没读到（比如雷柏鼠标要等它主动上报）：10 秒后补刷一次，不用等满一个周期
                user32.SetTimer(hwnd, RETRY_TIMER, RETRY_MS, None)
            return 0
        if msg == WM_TIMER:
            if wparam == RETRY_TIMER:
                user32.KillTimer(hwnd, RETRY_TIMER)
                self.refresh_now()
            else:
                self.on_timer()
            return 0
        if msg == self.msg_taskbar:               # 资源管理器重启，图标全丢了
            self.hicons.clear()
            self.update_icons()
            return 0
        if msg == WM_DESTROY:
            user32.KillTimer(hwnd, 1)
            user32.KillTimer(hwnd, RETRY_TIMER)
            self.remove_icons()
            user32.PostQuitMessage(0)             # 必须退出消息循环，否则留下僵尸进程
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self) -> int:
        hinst = kernel32.GetModuleHandleW(None)
        self.proc_ref = WNDPROC(self.wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = self.proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = WND_CLASS
        if not user32.RegisterClassExW(ctypes.byref(wc)) and \
                ctypes.get_last_error() != 1410:
            return 1
        self.hwnd = user32.CreateWindowExW(0, WND_CLASS, "BatteryMonitorTray", 0,
                                           0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            return 1
        self.update_icons()                       # 先放"正在读取"占位图标
        self.apply_timer()
        self.refresh_now()
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0


user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]


def run(debug: bool = False) -> int:
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:            # ERROR_ALREADY_EXISTS
        if is_running():
            return 0                              # 已经在跑了
    try:
        user32.SetProcessDPIAware()               # 不声明的话图标会被缩放发糊
    except Exception:
        pass
    try:
        return Tray(debug).run()
    except Exception:
        traceback.print_exc()
        return 1
