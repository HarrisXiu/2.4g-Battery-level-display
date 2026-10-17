# -*- coding: utf-8 -*-
"""Cherry 2.4G 键盘（实测：MX 8.3 Wireless，dongle 046A:01DB）

接口：usage page 0xFF1C / usage 0x92，64 字节收发，Report ID 0x04。
帧格式：  04 | 校验和 LE16 | 命令 | 参数 | 载荷…       校验和 = sum(帧[3:]) & 0xFFFF
电量：    请求 命令 0x1A 参数 0x06 → 回复 帧[3]==0x1A，电量百分比 = 帧[8]

注意：Cherry 官方软件在跑时会每 5 秒轮询一次，dongle 的回复会广播给所有句柄，
所以必须按命令字节过滤回复，不能拿到什么算什么。
"""

from __future__ import annotations

from hidraw import HidDevice, pad
from . import Driver, Reading, register

REPORT_ID = 0x04
FRAME_LEN = 64
CMD_BATTERY, ARG_BATTERY = 0x1A, 0x06


def build_frame(cmd: int, arg: int = 0, payload: bytes = b"") -> bytes:
    """按 Cherry 帧格式组帧（以后加别的命令可复用）。"""
    body = bytes([cmd, arg]) + payload
    ck = sum(body) & 0xFFFF
    return pad(bytes([REPORT_ID, ck & 0xFF, ck >> 8]) + body, FRAME_LEN)


@register
class CherryDriver(Driver):
    brand = "Cherry"
    kind = "keyboard"
    vids = (0x046A,)

    def match(self, ifaces) -> bool:
        return (bool(ifaces) and ifaces[0].vid in self.vids
                and any(i.usage_page == 0xFF1C for i in ifaces))

    def read(self, ifaces):
        iface = next(i for i in ifaces
                     if i.usage_page == 0xFF1C and i.output_len == FRAME_LEN)
        model = (iface.product or "").replace("Dongle", "").strip()
        name = f"Cherry {model} 键盘" if model else "Cherry 键盘"
        with HidDevice(iface) as dev:
            reply = dev.exchange(
                build_frame(CMD_BATTERY, ARG_BATTERY),
                accept=lambda r: len(r) > 8 and r[0] == REPORT_ID
                and r[3] == CMD_BATTERY,
                timeout=0.5, retries=3)
        r = Reading(key=self.key_of(ifaces), name=name, brand=self.brand,
                    kind=self.kind, source="Cherry 私有协议 (FF1C, 命令 0x1A)")
        if reply is None:
            r.error = "dongle 没有回复（键盘可能关机或没连上）"
        elif reply[8] > 100:
            r.error = f"电量字节异常：0x{reply[8]:02X}"
        else:
            r.level = reply[8]
        return [r]
