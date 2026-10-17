# -*- coding: utf-8 -*-
"""标准 HID 电量字段的读取（generic / rapoo 等驱动共用）。

单独放在这里、不注册任何驱动：如果别的驱动直接 import generic.py，
会把兜底驱动提前注册到前面，抢走本该由品牌驱动处理的设备。
"""

from __future__ import annotations

import time
from typing import Optional

from hidraw import HidDevice, HidError, HidP_Feature, HidP_Input
from . import Driver, Reading, register

BATTERY_USAGES = {
    (0x06, 0x20): "Battery Strength",
    (0x85, 0x64): "RelativeStateOfCharge",
    (0x85, 0x65): "AbsoluteStateOfCharge",
}


def _percent(value: int, logical_max: int) -> int:
    if logical_max and logical_max != 100:
        value = round(value * 100 / logical_max)
    return max(0, min(100, value))


def standard_battery(ifaces, listen: float = 1.0
                     ) -> Optional[tuple[int, str]]:
    """在这组接口里找标准电量字段，返回 (百分比, 来源)；找不到返回 None。"""
    for iface in ifaces:
        try:
            with HidDevice(iface, write=False) as dev:
                for cap in dev.value_caps(HidP_Feature):
                    name = BATTERY_USAGES.get((cap.UsagePage, cap.usage))
                    if not name:
                        continue
                    rep = dev.get_feature(cap.ReportID, iface.feature_len)
                    val = dev.usage_value(HidP_Feature, rep, cap)
                    if val is not None:
                        return (_percent(val, cap.LogicalMax),
                                f"标准 HID 电量字段 ({name}, Feature)")
                caps = [c for c in dev.value_caps(HidP_Input)
                        if (c.UsagePage, c.usage) in BATTERY_USAGES]
                end = time.monotonic() + listen
                while caps and dev.can_io and time.monotonic() < end:
                    rep = dev.read(timeout_ms=200)
                    if not rep:
                        continue
                    for cap in caps:
                        if cap.ReportID and rep[0] != cap.ReportID:
                            continue
                        val = dev.usage_value(HidP_Input, rep, cap)
                        if val is not None:
                            return (_percent(val, cap.LogicalMax),
                                    "标准 HID 电量字段 (Input Report)")
        except HidError:
            continue
    return None
