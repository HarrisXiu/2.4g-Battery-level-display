# -*- coding: utf-8 -*-
"""罗技 HID++ 2.0（实测：PRO X 2 / LIGHTSPEED 接收器 046D:C54D）

长报文 Report ID 0x11，共 20 字节：  11 | 设备索引 | 特性索引 | (函数<<4)|SW | 参数…
接收器上最多挂 6 台设备（索引 1-6）；直连设备索引是 0 或 0xFF。

电量特性，按顺序尝试：
  0x1004 统一电池   函数 1 getStatus   [4]=百分比 [5]=档位 [6]=状态
  0x1000 电池状态   函数 0             [4]=百分比 [6]=状态
  0x1001 电池电压   函数 0             [4:6]=毫伏(大端) [6]=标志，按曲线估算百分比

特性索引不是固定值，要先用根特性(索引 0)函数 0 按特性 ID 查，**索引在回复 [4]**。
"""

from __future__ import annotations

import itertools
from typing import Optional

from hidraw import HidDevice, pad
from . import Driver, Reading, register

REPORT_LONG, LONG_LEN = 0x11, 20
_sw_ids = itertools.cycle(range(1, 16))   # 每个请求换一个 SW ID（0 留给设备主动通知）
FEAT_NAME, FEAT_UNIFIED, FEAT_STATUS, FEAT_VOLTAGE = 0x0005, 0x1004, 0x1000, 0x1001
CANDIDATE_INDICES = [1, 2, 3, 4, 5, 6, 0, 0xFF]
HID_PAGES = (0xFF00, 0xFF43)

# 毫伏 → 百分比（锂电池放电曲线的近似，Solaar 也用这类表）
VOLTAGE_CURVE = [(4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60),
                 (3811, 50), (3778, 40), (3751, 30), (3717, 20), (3671, 10),
                 (3646, 5), (3579, 2), (3500, 0)]
LEVEL_FLAGS = [(0x08, 90), (0x04, 50), (0x02, 15), (0x01, 5)]   # 满/好/低/危急
DEVICE_KINDS = {0: "keyboard", 3: "mouse", 4: "mouse", 5: "mouse", 8: "headset"}

_known: dict[str, list[int]] = {}        # 接口路径 -> 上次有回应的设备索引
_scans: dict[str, int] = {}
_last_key: dict[str, str] = {}


def _hpp(dev: HidDevice, idx: int, feat: int, fn: int, params: bytes = b"",
         timeout: Optional[float] = None) -> Optional[bytes]:
    """发一次 HID++ 2.0 请求；返回回复，错误帧 / 超时返回 None。

    超时取 dev.hpp_timeout：扫描空槽位用短的（0.15 秒），已知设备 / 刚唤醒的设备用长的并重试，
    因为休眠的鼠标收到的第一个包可能只是把它唤醒。"""
    timeout = timeout or getattr(dev, "hpp_timeout", 0.15)
    # 每个请求用不同的 SW ID：超时后迟到的旧回复不会被当成下一个请求的答案
    # （根特性查询的回复不带特性 ID，不这样区分就会把索引对错位）
    sw = (fn << 4) | next(_sw_ids)
    req = pad(bytes([REPORT_LONG, idx, feat, sw]) + params, LONG_LEN)

    def mine(r: bytes) -> bool:
        if len(r) < 5 or r[0] != REPORT_LONG or r[1] != idx:
            return False
        return (r[2] == feat and r[3] == sw) or \
               (r[2] == 0xFF and r[3] == feat and r[4] == sw)   # 错误帧
    r = dev.exchange(req, mine, timeout=timeout, retries=2 if timeout > 0.2 else 1)
    return None if r is None or r[2] == 0xFF else r


def _feature_index(dev: HidDevice, idx: int, fid: int) -> Optional[int]:
    """特性 ID → 特性索引。0 = 设备不支持该特性；None = 设备根本没回应（槽位上没设备）。"""
    r = _hpp(dev, idx, 0x00, 0, bytes([fid >> 8, fid & 0xFF]))
    return r[4] if r else None


def _device_name(dev: HidDevice, idx: int) -> tuple[str, str]:
    fi = _feature_index(dev, idx, FEAT_NAME)
    if not fi:
        return "", "mouse"
    r = _hpp(dev, idx, fi, 0)
    if not r:
        return "", "mouse"
    total, name = r[4], b""
    while len(name) < min(total, 48):
        c = _hpp(dev, idx, fi, 1, bytes([len(name)]))
        if not c:
            break
        name += c[4:4 + min(16, total - len(name))]
    t = _hpp(dev, idx, fi, 2)
    kind = DEVICE_KINDS.get(t[4], "other") if t else "mouse"
    return name.decode("utf-8", "replace").strip("\x00 "), kind


def _from_voltage(mv: int) -> int:
    for volt, pct in VOLTAGE_CURVE:
        if mv >= volt:
            return pct
    return 0


def _battery(dev: HidDevice, idx: int):
    """返回 (百分比, 是否充电, 来源, 备注)；这个索引上没有设备 / 没有电池特性返回 None。"""
    fi = _feature_index(dev, idx, FEAT_UNIFIED)
    if fi is None:                           # 完全没回应：空槽位，别再浪费时间问别的特性
        return None
    if fi:
        r = _hpp(dev, idx, fi, 1)
        if r:
            pct, flags, st = r[4], r[5], r[6]
            note = ""
            if pct == 0:
                for bit, approx in LEVEL_FLAGS:
                    if flags & bit:
                        pct, note = approx, "设备只上报档位，百分比为估算"
                        break
            if st == 3:
                note = "已充满"
            return pct, st in (1, 2, 3), "HID++ 2.0 · 0x1004 统一电池", note
    fi = _feature_index(dev, idx, FEAT_STATUS)
    if fi:
        r = _hpp(dev, idx, fi, 0)
        if r:
            return r[4], r[6] in (1, 2, 4), "HID++ 2.0 · 0x1000 电池状态", ""
    fi = _feature_index(dev, idx, FEAT_VOLTAGE)
    if fi:
        r = _hpp(dev, idx, fi, 0)
        if r:
            mv = (r[4] << 8) | r[5]
            return (_from_voltage(mv), bool(r[6] & 0x80),
                    "HID++ 2.0 · 0x1001 电池电压", f"按 {mv} mV 估算")
    return None


@register
class LogitechDriver(Driver):
    brand = "罗技"
    kind = "mouse"
    vids = (0x046D,)

    def match(self, ifaces) -> bool:
        return (bool(ifaces) and ifaces[0].vid in self.vids
                and any(i.output_len == LONG_LEN and i.usage_page in HID_PAGES
                        for i in ifaces))

    def _probe(self, dev, ifaces, indices) -> list[Reading]:
        out = []
        for idx in indices:
            got = _battery(dev, idx)
            if got is None:
                continue
            pct, charging, source, note = got
            name, kind = _device_name(dev, idx)
            out.append(Reading(
                key=self.key_of(ifaces, str(idx)),
                name=name or ifaces[0].product or "罗技设备",
                brand=self.brand, kind=kind, level=max(0, min(100, pct)),
                charging=charging, source=source, note=note))
            _known.setdefault(dev.iface.path, []).append(idx)
        return out

    def read(self, ifaces):
        cands = [i for i in ifaces
                 if i.output_len == LONG_LEN and i.usage_page in HID_PAGES]
        iface = max(cands, key=lambda i: i.usage in (0x0002, 0x0202))
        path = iface.path
        _scans[path] = _scans.get(path, 0) + 1
        with HidDevice(iface) as dev:
            known = _known.pop(path, [])
            out: list[Reading] = []
            if known:                       # 已知设备：耐心等（它可能刚醒）
                dev.hpp_timeout = 0.4
                out = self._probe(dev, ifaces, known)
            if not out or _scans[path] % 10 == 0:   # 整表快速扫描，顺便发现新配对的设备
                dev.hpp_timeout = 0.15
                done = [int(r.key.split("#")[1]) for r in out]
                out += self._probe(dev, ifaces,
                                   [i for i in CANDIDATE_INDICES if i not in done])
            if not out:                     # 全无回应：可能鼠标刚睡着，慢速再试一遍
                dev.hpp_timeout = 0.5
                out = self._probe(dev, ifaces, CANDIDATE_INDICES[:6])
        if out:
            _last_key[path] = out[0].key
            return out
        r = self.fail(ifaces, "接收器没有回应（鼠标休眠请动一下；或设备没连上）",
                      iface.product or "罗技设备")
        r.key = _last_key.get(path, r.key)  # 沿用上次的 key，core 才能套上旧读数
        return [r]
