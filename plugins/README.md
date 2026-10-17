# 插件：用 Python 加新设备

把一个 `.py` 文件丢进这个文件夹，程序下次启动时自动加载（文件名以 `_` 开头的会被忽略）。
插件优先级**高于**内置驱动，所以也可以用来覆盖某个内置品牌的行为。
用 exe 的话，这个文件夹就在 exe 旁边。

不想自己写？把仓库根目录 [PROMPT.md](../PROMPT.md) 里的提示词交给 AI Agent，让它帮你摸协议、写插件。

## 接口

- `Driver`：一个品牌 / 协议的驱动
  - `brand`、`kind`（`keyboard` / `mouse` / `headset` / `other`）、`verified`（没在真机验证过就写 `False`，界面会标「未实测」）
  - `vids`：认领这些 VID 的设备；需要更细就重写 `match(ifaces)`
  - `read(ifaces)`：`ifaces` 是同一个 VID:PID 的全部 HID 接口（`hidraw.HidInterface`，有 `usage_page`、`usage`、`input_len`、`output_len`、`feature_len`、`product`……），返回 `Reading` 列表
  - `self.fail(ifaces, "原因", "显示名")`：读不到时返回一条带说明的失败读数
- `Reading`：`key`（全局唯一）、`name`、`brand`、`kind`、`level`（0–100，读不到为 `None`）、`charging`、`source`、`note`、`verified`
- `hidraw.HidDevice(iface)`：`write()` 发 Output Report、`read(timeout_ms)` 读 Input Report、`exchange()` 发请求并等符合条件的回复、`get_feature()` / `set_feature()`、`report_ids()`

设备读不到时返回失败读数即可，不要抛异常、不要长时间阻塞；程序会自动沿用这台设备上一次的读数。

## 请求-应答型（最常见）

发一条查询，等回复，取某个字节。参考 `drivers/cherry.py`。

```python
from drivers import Driver, Reading, register
from hidraw import HidDevice

@register
class MyMouse(Driver):
    brand = "我的品牌"
    kind = "mouse"
    verified = True
    vids = (0x1234,)

    def read(self, ifaces):
        iface = next(i for i in ifaces if i.usage_page == 0xFF00 and i.output_len)
        with HidDevice(iface) as dev:
            reply = dev.exchange(b"\x08\x01\x00",                 # 请求（首字节 = Report ID），自动补 0
                                 accept=lambda r: r[1] == 0x01,   # 只认自己那条回复
                                 timeout=0.5, retries=3)
        if reply is None:
            return [self.fail(ifaces, "设备没有回复（休眠？）", "我的鼠标")]
        return [Reading(key=self.key_of(ifaces), name="我的鼠标", brand=self.brand,
                        kind=self.kind, level=reply[4], source="我的协议")]
```

## 主动推送型

有的设备没有查询命令，只在被使用时周期性推送状态（例如雷柏 VT 系列）。
这时起一个常驻线程一直监听、记住最近一份，`read()` 直接取缓存。完整写法见 `drivers/rapoo.py` 的 `_Listener`。

## 多级协议

先查特性索引、再调函数，或者一个接收器挂多台设备（每台返回一条 `Reading`，`key` 用 `self.key_of(ifaces, "编号")` 区分）。参考 `drivers/logitech.py`。

不会写代码的话，简单协议可以在 `devices.json` 里写一条声明式配置，见根目录 README。
