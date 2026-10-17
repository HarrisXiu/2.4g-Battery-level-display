# -*- coding: utf-8 -*-
"""drivers —— 设备驱动的注册接口（也是给你加新设备用的扩展点）

三种加设备的方式，从简单到灵活：

1. devices.json    声明式：写一条 JSON（VID、请求字节、电量下标），不写代码
2. plugins/*.py    丢一个 Python 文件进去，里面继承 Driver 并 @register
3. drivers/*.py    内置驱动，写法同 plugins

加载顺序 = 优先级：plugins → devices.json → 内置品牌驱动 → generic（兜底）。
同一个 VID:PID 只交给第一个 match() 为真的驱动，所以 plugins 可以覆盖内置驱动。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from paths import ROOT


# --------------------------------------------------------------------------
# 读数
# --------------------------------------------------------------------------
@dataclass
class Reading:
    key: str                       # 全局唯一，如 "046A:01DB" / "046D:C54D#1"
    name: str                      # 显示名
    brand: str
    kind: str = "other"            # keyboard / mouse / headset / other
    level: Optional[int] = None    # 0-100；None = 没读到
    charging: Optional[bool] = None
    source: str = ""               # 用的什么协议
    error: str = ""                # level 为 None 时的原因
    verified: bool = True          # False = 未经实机验证
    note: str = ""                 # 附加信息（固件、电压…）
    stale: bool = False            # True = 这次没读到，level 是上一次的旧读数
    ts: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.level is not None


# --------------------------------------------------------------------------
# 驱动基类
# --------------------------------------------------------------------------
class Driver:
    """一个品牌 / 协议的驱动。

    * match(ifaces)  ifaces 是同一个 VID:PID 的全部接口，返回 True 表示认领
    * read(ifaces)   返回 Reading 列表（一个接收器可以挂多台设备）
    """
    brand = ""
    kind = "other"
    verified = True
    vids: tuple = ()               # 默认 match 用

    def match(self, ifaces) -> bool:
        return bool(ifaces) and ifaces[0].vid in self.vids

    def read(self, ifaces) -> list[Reading]:
        raise NotImplementedError

    # ---- 小工具 --------------------------------------------------------
    @staticmethod
    def key_of(ifaces, suffix: str = "") -> str:
        return ifaces[0].vid_pid + (f"#{suffix}" if suffix else "")

    def fail(self, ifaces, error: str, name: str = "") -> Reading:
        return Reading(key=self.key_of(ifaces), name=name or self.brand,
                       brand=self.brand, kind=self.kind, error=error,
                       verified=self.verified)


_ORDER = ("plugin", "json", "builtin", "generic")
_PHASES: dict[str, list[Driver]] = {p: [] for p in _ORDER}
_phase = "builtin"          # 当前正在加载哪一类；register() 据此归类


def register(cls):
    """类装饰器：实例化并加入当前阶段的注册表。"""
    _PHASES[_phase].append(cls())
    return cls


def add_driver(driver: Driver, phase: str) -> None:
    _PHASES[phase].append(driver)


def _import_builtin(name: str, phase: str) -> None:
    global _phase
    old, _phase = _phase, phase
    try:
        importlib.import_module(f"drivers.{name}")
    finally:
        _phase = old


def _load_plugins() -> list[str]:
    global _phase
    errors: list[str] = []
    pdir = os.path.join(ROOT, "plugins")
    if not os.path.isdir(pdir):
        return errors
    old, _phase = _phase, "plugin"
    try:
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"plugins.{fn[:-3]}", os.path.join(pdir, fn))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:                      # 一个坏插件不拖垮全部
                errors.append(f"plugins/{fn}: {e}")
    finally:
        _phase = old
    return errors


_loaded = False
load_errors: list[str] = []


def load_all() -> list[Driver]:
    """加载全部驱动（只做一次），返回按优先级排好的列表。"""
    global _loaded
    if _loaded:
        return _all()
    _loaded = True
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    load_errors.extend(_load_plugins())
    try:
        from . import declarative
        declarative.load(add_driver, load_errors)
    except Exception as e:
        load_errors.append(f"devices.json: {e}")
    for name in ("cherry", "logitech", "atk", "vgn", "rapoo"):
        try:
            _import_builtin(name, "builtin")
        except Exception as e:
            load_errors.append(f"drivers/{name}.py: {e}")
    try:
        _import_builtin("generic", "generic")
    except Exception as e:
        load_errors.append(f"drivers/generic.py: {e}")
    return _all()


def _all() -> list[Driver]:
    return [d for p in _ORDER for d in _PHASES[p]]
