# -*- coding: utf-8 -*-
"""兜底驱动：设备只要按 HID 标准声明了电量字段就能读，不用写专用协议。

识别的字段（Feature Report 或 Input Report 都行）：
    Generic Device Controls 页 0x06 / Battery Strength 0x20
    Battery System 页 0x85 / RelativeStateOfCharge 0x64、AbsoluteStateOfCharge 0x65
"""

from __future__ import annotations

import time

from . import Driver, Reading, register
from ._stdhid import standard_battery


_negative: dict[str, float] = {}          # VID:PID -> 上次确认"没有电量字段"的时间
NEGATIVE_TTL = 600.0


@register
class GenericDriver(Driver):
    brand = ""

    def match(self, ifaces) -> bool:
        if not ifaces or all(i.reserved for i in ifaces):
            return False
        return time.time() - _negative.get(ifaces[0].vid_pid, 0) > NEGATIVE_TTL

    def read(self, ifaces):
        got = standard_battery(ifaces)
        if got is None:
            _negative[ifaces[0].vid_pid] = time.time()
            return []
        pct, source = got
        i = ifaces[0]
        return [Reading(key=self.key_of(ifaces),
                        name=i.product or f"HID 设备 {i.vid_pid}",
                        brand=i.manufacturer or "未知品牌", level=pct,
                        source=source)]
