# -*- coding: utf-8 -*-
"""ATK / VXE / VGN 一类无线鼠标共用的两种私有协议（Report ID 0x08）。

协议 2（Nordic 54L15，实测过：ATK 373B:1216）
    接口 usage page 0xFF05，64 字节
    请求  08 7D 72 02 00 01 07 01 00…
    回复  [1]==0x72 且 [5]==0x07，电量 = [7]

协议 1（Nordic 52840，社区资料，**本机未实测**）
    接口 usage page 0xFF02，17 字节
    请求  08 04 00×14 + 校验字节，校验 = (0x55 - sum(前 16 字节)) & 0xFF
    回复  [1]==0x04，电量 = [6]，[7] 非 0 表示正在有线连接
"""

from __future__ import annotations

from typing import Optional

from hidraw import HidDevice, pad
from . import Reading


def proto2(ifaces, brand: str, kind: str, key: str, name: str
           ) -> Optional[Reading]:
    iface = next((i for i in ifaces
                  if i.usage_page == 0xFF05 and i.output_len == 64), None)
    if iface is None:
        return None
    r = Reading(key=key, name=name, brand=brand, kind=kind,
                source="厂商协议 2 (FF05, 64B)")
    with HidDevice(iface) as dev:
        reply = dev.exchange(
            pad(bytes([0x08, 0x7D, 0x72, 0x02, 0x00, 0x01, 0x07, 0x01]), 64),
            accept=lambda x: len(x) > 7 and x[1] == 0x72 and x[5] == 0x07,
            timeout=0.4, retries=3)
    if reply is None:
        r.error = "鼠标没有回复（多半在休眠，动一下鼠标再试）"
    elif reply[7] > 100:
        r.error = f"电量字节异常：0x{reply[7]:02X}"
    else:
        r.level = reply[7]
    return r


def proto1(ifaces, brand: str, kind: str, key: str, name: str
           ) -> Optional[Reading]:
    iface = next((i for i in ifaces
                  if i.usage_page == 0xFF02 and i.output_len == 17), None)
    if iface is None:
        return None
    head = bytes([0x08, 0x04]) + bytes(14)
    req = head + bytes([(0x55 - sum(head)) & 0xFF])
    r = Reading(key=key, name=name, brand=brand, kind=kind, verified=False,
                source="厂商协议 1 (FF02, 17B) · 未实测")
    with HidDevice(iface) as dev:
        reply = dev.exchange(
            req, accept=lambda x: len(x) > 7 and x[1] == 0x04,
            timeout=0.4, retries=3)
    if reply is None:
        r.error = "鼠标没有回复（多半在休眠，动一下鼠标再试）"
    elif reply[6] > 100:
        r.error = f"电量字节异常：0x{reply[6]:02X}"
    else:
        r.level, r.charging = reply[6], bool(reply[7])
    return r
