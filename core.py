# -*- coding: utf-8 -*-
"""core.py —— 扫描：枚举 HID → 按 VID:PID 分组 → 交给第一个认领的驱动读电量"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field

import drivers
import hidraw
from drivers import Reading


@dataclass
class ScanResult:
    readings: list[Reading] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)    # 驱动加载 / 运行异常


_last_good: dict[str, Reading] = {}     # key -> 最近一次成功的读数
STALE_MAX = 24 * 3600                    # 旧读数最多沿用 24 小时


def _remember(r: Reading) -> Reading:
    """设备休眠这类瞬时失败时，沿用上次读数并标记 stale，别让图标一会儿数字一会儿 --。"""
    if r.ok:
        _last_good[r.key] = r
        return r
    old = _last_good.get(r.key)
    if old is not None and time.time() - old.ts < STALE_MAX:
        r.level, r.charging, r.ts = old.level, old.charging, old.ts
        r.name, r.kind, r.stale = old.name, old.kind, True
        r.source = old.source
    return r


def group_by_device(ifaces) -> dict[tuple, list]:
    groups: dict[tuple, list] = {}
    for i in ifaces:
        groups.setdefault((i.vid, i.pid), []).append(i)
    return groups


def scan() -> ScanResult:
    res = ScanResult(errors=list(drivers.load_errors))
    all_drivers = drivers.load_all()
    try:
        groups = group_by_device(hidraw.enumerate_interfaces())
    except Exception as e:
        res.errors.append(f"枚举 HID 失败：{e}")
        return res

    for ifaces in groups.values():
        for d in all_drivers:
            try:
                if not d.match(ifaces):
                    continue
            except Exception:
                continue
            try:
                res.readings.extend(_remember(r) for r in d.read(ifaces))
            except Exception as e:
                if getattr(d, "debug", False):
                    traceback.print_exc()
                res.readings.append(_remember(d.fail(ifaces, f"读取出错：{e}")))
            break

    return res
