# -*- coding: utf-8 -*-
"""VGN / VXE 无线鼠标（VID 0x3554，Compx 方案）。

**未实测**：与 ATK 同一套 Report ID 0x08 私有协议，先试协议 1 再试协议 2。
如果你的型号读不出来，用 `python main.py --sniff 3554:XXXX` 抓官方驱动的报文，
再把结果写进 devices.json（见 README）。
"""

from __future__ import annotations

from . import Driver, register
from . import _compx


@register
class VgnDriver(Driver):
    brand = "VGN"
    kind = "mouse"
    verified = False
    vids = (0x3554,)

    def read(self, ifaces):
        name = f"VGN {ifaces[0].product}" if ifaces[0].product else "VGN 鼠标"
        key = self.key_of(ifaces)
        for proto in (_compx.proto1, _compx.proto2):
            r = proto(ifaces, self.brand, self.kind, key, name)
            if r is not None and r.ok:
                r.verified = False
                return [r]
        r = _compx.proto1(ifaces, self.brand, self.kind, key, name) \
            or _compx.proto2(ifaces, self.brand, self.kind, key, name)
        if r is None:
            return [self.fail(ifaces, "没找到已知的厂商接口（FF02 / FF05）", name)]
        r.verified = False
        return [r]
