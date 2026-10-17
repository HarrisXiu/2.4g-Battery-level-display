# -*- coding: utf-8 -*-
"""雷柏 Rapoo 无线鼠标（VID 0x24AE）——无需雷柏驱动，直接走 HID

实测：VT3S Air Max（接收器 24AE:14A2）。
协议来自雷柏官方网页驱动 RAPOO HUB（hub.rapoo.cn）里 driver="VT_nrf54L" 的实现，
同一套协议覆盖下表 77 个型号（VT0~VT9 各代、ESM6xx 等）。

接口（usage page 0xFF00）：
    usage 0x02  19 字节 Input Report 0x07 = 「鼠标用户数据」，鼠标醒着时约每 3 秒推送一次
    usage 0x0E  33 字节 Output Report 0x06 = 命令；回复从 Feature Report 0x08 读（首字节 1=成功 2=忙）
Report 0x07 布局（下标含 Report ID）：
    [1] 低 4 位连接协议 / 高 4 位传感器   [2] DPI 档位   [3:5][5:7] X/Y DPI（小端）
    [7] 电池状态（1 = 未充电，其他 = 充电中）   [8] 电量百分比
    [13:15] 鼠标有线 PID   [18] bit7 = 无线已连接，低 7 位 = 信号强度
读电量：这款鼠标没有「查询电量」的命令（网页驱动也只是被动等 0x07），而且只在鼠标被使用时
每 ~3 秒推一次，静止一会儿就不推了。所以这里起一个常驻的后台线程一直监听 usage 0x02，
记住最近一份 0x07；每次刷新直接取它。全程只读，不向鼠标发送任何命令。
（命令行 --once 这种一次性进程没有常驻线程，只能现场等几秒，鼠标静止时会读不到。）

不在表里的雷柏设备（其他方案）退回标准 HID 电量字段。
"""

from __future__ import annotations

import threading
import time

from hidraw import HidDevice, HidError
from . import Driver, Reading, register
from ._stdhid import standard_battery

REPORT_USER = 0x07
WAIT_S = 3.5                       # 还没收到过上报时，本次刷新最多等多久（推送周期约 3 秒）
IDLE_S = 10 * 60                   # 超过这么久没有新上报，视为鼠标休眠（显示的是那次的读数）
VERIFIED_PIDS = {0x14A2, 0x46A2}   # 实测过的：VT3S Air Max

# 型号表（RAPOO HUB 网页驱动，driver = VT_nrf54L）：型号|有线 PID[,接收器 PID]
_VT_NRF54L = (
    "ESM612ACE|17997;ESM612MAX|18049;ESM612PRO|17969;ESM622MAX|17975;ESM622PRO|17970;"
    "ESM652PRO|17971;ESM672MAX|17984;ESM672PRO|17973;VT0 MAX MASTER|17994,5194;"
    "VT0 MAX|17952,5152;VT0|17936,5136;VT0 Air MAX|18081,5281;VT1 MAX|17988,5188;"
    "VT1|17941,5141;VT1S MAX V2|19210,6922;VT1S V2|18026,5226;VT2 MAX MASTER V2|18037,5237;"
    "VT2 MAX V2|19209,6921;VT2 MAX|17955,5155;VT2 V2|18024,5224;VT2|17954,5154;"
    "VT2 Air MAX V2|19218,6930;VT2K MAX|18084,5284;VT2S MAX MASTER V2|18038,5238;"
    "VT2S MAX V2|19204,6916;VT2S V2|18013,5213;VT2S Air MAX V2|19219,6931;"
    "VT3 MAX MASTER V2|18029,5229;VT3 MAX V2|19206,6918;VT3 MAX|17943,5143;"
    "VT3 PRO V2|18085,5285;VT3 V2|18018,5218;VT3|17938,5138;VT3 Air MAX V2|19212,6924;"
    "VT3S MAX MASTER V2|18030,5230;VT3S MAX MASTER|17995,5195;VT3S MAX V2|19207,6919;"
    "VT3S MAX|17953,5153;VT3S PRO V2|18086,5286;VT3S V2|18020,5220;VT3S|17937,5137;"
    "VT3S Air MAX V2|19213,6925;VT3S Air Max|18082,5282;VT4 MAX MASTER V2|18039,5239;"
    "VT4 MAX V2|19203,6915;VT4 V2|18011,5211;VT4 Air MAX V2|19220,6932;VT6 MAX|18002,5202;"
    "VT6|18001,5201;VT7 MAX MASTER V2|18032,5232;VT7 MAX V2|19205,6917;VT7 MAX|17942,5142;"
    "VT7 PRO V2|18087,5287;VT7 V2|18016,5216;VT7|17939,5139;VT7 Air MAX V2|19214,6926;"
    "VT7S MAX MASTER V2|18033,5233;VT7S MAX V2|19202,6914;VT7S PRO V2|18088,5288;"
    "VT7S V2|18009,5209;VT7S Air MAX V2|19215,6927;VT8 MAX MASTER V2|18040,5240;"
    "VT8 MAX V2|19211,6923;VT8 V2|18028,5228;VT8 Air MAX V2|19221,6933;"
    "VT9 MAX MASTER V2|18035,5235;VT9 MAX V2|19208,6920;VT9 MAX|17944,5144;"
    "VT9 PRO V2|18089,5289;VT9 V2|18022,5222;VT9|17940,5140;VT9 Air MAX V2|19216,6928;"
    "VT9S MAX MASTER V2|18036,5236;VT9S MAX V2|19201,6913;VT9S PRO V2|18090,5290;"
    "VT9S V2|18003,5203;VT9S Air MAX V2|19217,6929"
)
MODELS: dict[int, tuple[str, bool]] = {}          # PID -> (型号, 是否接收器/无线)
for _item in _VT_NRF54L.split(";"):
    _name, _pids = _item.split("|")
    for _k, _pid in enumerate(_pids.split(",")):
        MODELS[int(_pid)] = (_name, _k == 1)


class _Listener(threading.Thread):
    """常驻监听一个接收器的 Report 0x07，记住最近一份。拔掉接收器后线程自己结束。"""

    def __init__(self, iface):
        super().__init__(daemon=True, name=f"rapoo-{iface.vid_pid}")
        self.iface = iface
        self.last: tuple[bytes, float] | None = None
        self.got = threading.Event()

    def run(self):
        try:
            with HidDevice(self.iface, write=False) as d:
                while True:
                    x = d.read(timeout_ms=1000)
                    if x and len(x) > 8 and x[0] == REPORT_USER:
                        self.last = (x, time.time())
                        self.got.set()
        except HidError:
            pass                                     # 设备拔掉了


_listeners: dict[str, _Listener] = {}
_lock = threading.Lock()


def _listener(iface) -> _Listener:
    with _lock:
        ls = _listeners.get(iface.path)
        if ls is None or not ls.is_alive():
            ls = _listeners[iface.path] = _Listener(iface)
            ls.start()
        return ls


def _vt_read(ifaces, ev, name: str, wireless: bool) -> Reading:
    r = Reading(key=ifaces[0].vid_pid, name=name, brand="雷柏", kind="mouse",
                source="雷柏 VT 协议 · 用户数据报告 0x07",
                verified=ifaces[0].pid in VERIFIED_PIDS)
    ls = _listener(ev)
    if ls.last is None:
        ls.got.wait(WAIT_S)                          # 刚启动还没收到过：现场等一会儿
    if ls.last is None:
        r.error = "还没收到鼠标的电量上报（动一下鼠标，几秒后就会出现）"
        return r
    rep, when = ls.last
    r.ts = when
    if wireless and len(rep) > 18 and not rep[18] >> 7:
        r.error = "鼠标未连接接收器（关机或超出范围）"
    elif rep[8] > 100:
        r.error = f"电量字节异常：0x{rep[8]:02X}"
    else:
        r.level, r.charging = rep[8], rep[7] != 1
        r.stale = time.time() - when > IDLE_S
        if r.stale:
            r.error = "鼠标静止中，没有新的上报"
        if wireless and len(rep) > 18:
            r.note = f"信号 {rep[18] & 0x7F}"
    return r


@register
class RapooDriver(Driver):
    brand = "雷柏"
    kind = "mouse"
    vids = (0x24AE,)

    def read(self, ifaces):
        i = ifaces[0]
        model, wireless = MODELS.get(i.pid, (None, True))
        name = f"雷柏 {model}" if model else (f"雷柏 {i.product}" if i.product else "雷柏设备")
        ev = next((x for x in ifaces if x.usage_page == 0xFF00 and x.usage == 0x02
                   and x.input_len == 19), None)
        if ev is not None:
            return [_vt_read(ifaces, ev, name, wireless)]
        got = standard_battery(ifaces)
        if got is None:
            r = self.fail(ifaces, "这款雷柏设备的协议还没收录（不是 VT 系列方案）", name)
            r.verified = False
            return [r]
        pct, source = got
        return [Reading(key=self.key_of(ifaces), name=name, brand=self.brand,
                        kind=self.kind, level=pct, source=source, verified=False)]
