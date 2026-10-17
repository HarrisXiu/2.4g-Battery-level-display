# -*- coding: utf-8 -*-
"""ATK 无线鼠标（VID 0x373B）。协议 2 已在参考资料里验证过；协议 1 作为后备。"""

from __future__ import annotations

from . import Driver, register
from . import _compx


@register
class AtkDriver(Driver):
    brand = "ATK"
    kind = "mouse"
    vids = (0x373B,)

    def read(self, ifaces):
        name = f"ATK {ifaces[0].product}" if ifaces[0].product else "ATK 鼠标"
        key = self.key_of(ifaces)
        r = (_compx.proto2(ifaces, self.brand, self.kind, key, name)
             or _compx.proto1(ifaces, self.brand, self.kind, key, name))
        if r is None:
            return [self.fail(ifaces, "没找到已知的厂商接口（FF05 / FF02）", name)]
        if not r.ok and r.verified:                      # 协议 2 失败再试协议 1
            alt = _compx.proto1(ifaces, self.brand, self.kind, key, name)
            if alt is not None and alt.ok:
                return [alt]
        return [r]
