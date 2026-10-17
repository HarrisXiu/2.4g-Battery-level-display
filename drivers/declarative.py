# -*- coding: utf-8 -*-
"""devices.json 声明式驱动：不写代码，用一条 JSON 描述"发什么、电量在哪个字节"。

{
  "devices": [{
    "name": "我的鼠标",          // 显示名
    "brand": "ATK", "kind": "mouse",
    "vid": "373B", "pid": "1216",   // pid 可省略；数字或十六进制字符串都行
    "usage_page": "FF05",          // 用哪个接口（可省略 = 第一个能收发的）
    "mode": "output",              // output = 写 Output Report 等 Input 回复
                                   // feature = SetFeature 后 GetFeature
    "report_length": 64,           // 报文总长（含 Report ID），省略 = 接口声明的长度
    "request": "08 7D 72 02 00 01 07 01",   // 十六进制，不足部分补 0；第一个字节是 Report ID
    "expect": {"1": "72", "5": "07"},       // 回复里这些下标必须等于这些值（过滤别人的回复）
    "level_offset": 7,             // 电量字节下标（从 Report ID 算第 0 个）
    "scale": 1, "level_max": 100,  // 百分比 = 字节 × scale；超过 level_max 视为无效
    "charging_offset": null,       // 可选：该字节非 0 表示充电
    "wait_ms": 120, "retries": 3, "verified": true
  }]
}
"""

from __future__ import annotations

import json
import os
import time

from hidraw import HidDevice, pad
from . import Driver, Reading, ROOT

CONFIG = os.path.join(ROOT, "devices.json")


def _num(v) -> int:
    return v if isinstance(v, int) else int(str(v), 16)


class DeclDriver(Driver):
    def __init__(self, spec: dict):
        self.spec = spec
        self.brand = spec.get("brand", "自定义")
        self.kind = spec.get("kind", "other")
        self.verified = bool(spec.get("verified", False))
        self.vid = _num(spec["vid"])
        self.pid = _num(spec["pid"]) if spec.get("pid") not in (None, "") else None
        self.page = _num(spec["usage_page"]) if spec.get("usage_page") else None
        self.mode = spec.get("mode", "output")
        self.request = bytes.fromhex(spec["request"])
        self.expect = {int(k): _num(v) for k, v in spec.get("expect", {}).items()}

    def _iface(self, ifaces):
        for i in ifaces:
            if self.page is not None and i.usage_page != self.page:
                continue
            if (i.output_len if self.mode == "output" else i.feature_len):
                return i
        return None

    def match(self, ifaces) -> bool:
        return (bool(ifaces) and ifaces[0].vid == self.vid
                and (self.pid is None or ifaces[0].pid == self.pid)
                and self._iface(ifaces) is not None)

    def _ok(self, r: bytes) -> bool:
        return all(len(r) > o and r[o] == v for o, v in self.expect.items())

    def read(self, ifaces):
        s, iface = self.spec, self._iface(ifaces)
        out = Reading(key=self.key_of(ifaces) + f"@{s.get('name', 'json')}",
                      name=s.get("name", ifaces[0].product or "自定义设备"),
                      brand=self.brand, kind=self.kind,
                      source="devices.json 声明式协议", verified=self.verified)
        length = int(s.get("report_length") or
                     (iface.output_len if self.mode == "output" else iface.feature_len))
        req = pad(self.request, length)
        retries = int(s.get("retries", 3))
        reply = None
        with HidDevice(iface) as dev:
            if self.mode == "feature":
                for _ in range(retries):
                    dev.set_feature(req)
                    time.sleep(int(s.get("wait_ms", 120)) / 1000)
                    r = dev.get_feature(req[0], length)
                    if self._ok(r):
                        reply = r
                        break
            else:
                reply = dev.exchange(req, self._ok, retries=retries,
                                     timeout=int(s.get("wait_ms", 300)) / 1000)
        off = int(s.get("level_offset", 0))
        if reply is None or len(reply) <= off:
            out.error = "设备没有回复（可能在休眠，动一下 / 开机后重试）"
            return [out]
        raw = reply[off]
        if raw > int(s.get("level_max", 255)):
            out.error = f"电量字节异常：0x{raw:02X}"
            return [out]
        out.level = max(0, min(100, raw * int(s.get("scale", 1))))
        co = s.get("charging_offset")
        if co is not None and len(reply) > int(co):
            out.charging = bool(reply[int(co)])
        return [out]


def load(add, errors: list[str]) -> None:
    if not os.path.exists(CONFIG):
        return
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        errors.append(f"devices.json 读取失败：{e}")
        return
    for n, spec in enumerate(data.get("devices", []), 1):
        try:
            add(DeclDriver(spec), "json")
        except Exception as e:
            errors.append(f"devices.json 第 {n} 条无效：{e}")
