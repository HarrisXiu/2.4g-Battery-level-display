# -*- coding: utf-8 -*-
"""hidraw.py —— 纯 ctypes 的 Windows HID 访问层（无第三方依赖）

* enumerate_interfaces()  枚举系统里所有 HID 接口（一个顶层集合 = 一个接口）
* HidDevice               打开一个接口，收发 Output / Feature / Input 报告

关于句柄：读和写各开一个句柄。读句柄带 FILE_FLAG_OVERLAPPED，用事件等待超时，
超时后 CancelIoEx；写句柄是同步的。**不要在同一个同步句柄上让阻塞的 ReadFile
和 WriteFile 并发**，那会直接卡死/杀掉进程。
"""

from __future__ import annotations

import ctypes
import re
import struct
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

USHORT = ctypes.c_ushort
UCHAR = ctypes.c_ubyte
ULONG = ctypes.c_ulong
LONG = ctypes.c_long


class HidError(OSError):
    pass


# --------------------------------------------------------------------------
# 结构体
# --------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", ULONG), ("VendorID", USHORT), ("ProductID", USHORT),
                ("VersionNumber", USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", USHORT), ("UsagePage", USHORT),
                ("InputReportByteLength", USHORT),
                ("OutputReportByteLength", USHORT),
                ("FeatureReportByteLength", USHORT),
                ("Reserved", USHORT * 17),
                ("NumberLinkCollectionNodes", USHORT),
                ("NumberInputButtonCaps", USHORT),
                ("NumberInputValueCaps", USHORT),
                ("NumberInputDataIndices", USHORT),
                ("NumberOutputButtonCaps", USHORT),
                ("NumberOutputValueCaps", USHORT),
                ("NumberOutputDataIndices", USHORT),
                ("NumberFeatureButtonCaps", USHORT),
                ("NumberFeatureValueCaps", USHORT),
                ("NumberFeatureDataIndices", USHORT)]


class _Range(ctypes.Structure):
    _fields_ = [("UsageMin", USHORT), ("UsageMax", USHORT),
                ("StringMin", USHORT), ("StringMax", USHORT),
                ("DesignatorMin", USHORT), ("DesignatorMax", USHORT),
                ("DataIndexMin", USHORT), ("DataIndexMax", USHORT)]


class _NotRange(ctypes.Structure):
    _fields_ = [("Usage", USHORT), ("Reserved1", USHORT),
                ("StringIndex", USHORT), ("Reserved2", USHORT),
                ("DesignatorIndex", USHORT), ("Reserved3", USHORT),
                ("DataIndex", USHORT), ("Reserved4", USHORT)]


class _CapsUnion(ctypes.Union):
    _fields_ = [("Range", _Range), ("NotRange", _NotRange)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", USHORT), ("ReportID", UCHAR), ("IsAlias", UCHAR),
                ("BitField", USHORT), ("LinkCollection", USHORT),
                ("LinkUsage", USHORT), ("LinkUsagePage", USHORT),
                ("IsRange", UCHAR), ("IsStringRange", UCHAR),
                ("IsDesignatorRange", UCHAR), ("IsAbsolute", UCHAR),
                ("HasNull", UCHAR), ("Reserved", UCHAR),
                ("BitSize", USHORT), ("ReportCount", USHORT),
                ("Reserved2", USHORT * 5),
                ("UnitsExp", ULONG), ("Units", ULONG),
                ("LogicalMin", LONG), ("LogicalMax", LONG),
                ("PhysicalMin", LONG), ("PhysicalMax", LONG),
                ("u", _CapsUnion)]

    @property
    def usage(self) -> int:
        return self.u.Range.UsageMin if self.IsRange else self.u.NotRange.Usage


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", ctypes.c_void_p)]


# --------------------------------------------------------------------------
# 原型
# --------------------------------------------------------------------------
_P = ctypes.POINTER
setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [_P(GUID), wintypes.LPCWSTR,
                                          ctypes.c_void_p, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, _P(GUID), wintypes.DWORD,
    _P(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p, _P(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, _P(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

hid.HidD_GetHidGuid.restype = None
hid.HidD_GetHidGuid.argtypes = [_P(GUID)]
hid.HidD_GetAttributes.restype = wintypes.BOOL
hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, _P(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, _P(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.restype = wintypes.BOOL
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.restype = LONG
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, _P(HIDP_CAPS)]
hid.HidP_GetValueCaps.restype = LONG
hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, _P(HIDP_VALUE_CAPS),
                                  _P(USHORT), ctypes.c_void_p]
hid.HidP_GetButtonCaps.restype = LONG
hid.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, _P(USHORT),
                                   ctypes.c_void_p]
hid.HidP_GetUsageValue.restype = LONG
hid.HidP_GetUsageValue.argtypes = [ctypes.c_int, USHORT, USHORT, USHORT,
                                   _P(ULONG), ctypes.c_void_p,
                                   ctypes.c_void_p, ULONG]
for _n in ("HidD_GetProductString", "HidD_GetManufacturerString",
           "HidD_GetFeature", "HidD_SetFeature", "HidD_SetOutputReport"):
    getattr(hid, _n).restype = wintypes.BOOL
    getattr(hid, _n).argtypes = [ctypes.c_void_p, ctypes.c_void_p, ULONG]

k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p]
k32.CloseHandle.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.ReadFile.restype = wintypes.BOOL
k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         _P(wintypes.DWORD), ctypes.c_void_p]
k32.WriteFile.restype = wintypes.BOOL
k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                          _P(wintypes.DWORD), ctypes.c_void_p]
k32.CreateEventW.restype = ctypes.c_void_p
k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                             wintypes.LPCWSTR]
k32.ResetEvent.restype = wintypes.BOOL
k32.ResetEvent.argtypes = [ctypes.c_void_p]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
k32.CancelIoEx.restype = wintypes.BOOL
k32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
k32.GetOverlappedResult.restype = wintypes.BOOL
k32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    _P(wintypes.DWORD), wintypes.BOOL]

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
INVALID_HANDLE = ctypes.c_void_p(-1).value
ERROR_IO_PENDING, ERROR_OPERATION_ABORTED = 997, 995
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 0x102
HIDP_STATUS_SUCCESS = 0x00110000
HidP_Input, HidP_Output, HidP_Feature = 0, 1, 2


def _bad(h) -> bool:
    return h in (None, 0, INVALID_HANDLE)


def _open(path: str, access: int, flags: int = 0):
    h = k32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, flags, None)
    return None if _bad(h) else h


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------
# 系统独占的顶层集合：不能以读写方式打开，只能 access=0 读属性
RESERVED_USAGES = {(0x01, 0x02), (0x01, 0x06), (0x01, 0x07), (0x0D, 0x04),
                   (0x0D, 0x05)}


@dataclass
class HidInterface:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    input_len: int
    output_len: int
    feature_len: int
    product: str = ""
    manufacturer: str = ""

    @property
    def vid_pid(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    @property
    def reserved(self) -> bool:
        return (self.usage_page, self.usage) in RESERVED_USAGES

    def __str__(self) -> str:
        return (f"{self.vid_pid} {self.usage_page:04X}:{self.usage:04X} "
                f"in={self.input_len} out={self.output_len} "
                f"feat={self.feature_len}  {self.manufacturer} {self.product}")


def _wstr(fn, h) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if fn(h, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


def _probe(path: str) -> Optional[HidInterface]:
    h = _open(path, 0)
    if h is None:
        return None
    try:
        attr = HIDD_ATTRIBUTES()
        attr.Size = ctypes.sizeof(attr)
        if hid.HidD_GetAttributes(h, ctypes.byref(attr)):
            vid, pid = attr.VendorID, attr.ProductID
        else:
            m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path, re.I)
            vid, pid = (int(m.group(1), 16), int(m.group(2), 16)) if m else (0, 0)
        ppd = ctypes.c_void_p()
        caps = HIDP_CAPS()
        if not hid.HidD_GetPreparsedData(h, ctypes.byref(ppd)):
            return None
        try:
            if hid.HidP_GetCaps(ppd, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                return None
        finally:
            hid.HidD_FreePreparsedData(ppd)
        return HidInterface(
            path=path, vid=vid, pid=pid, usage_page=caps.UsagePage,
            usage=caps.Usage, input_len=caps.InputReportByteLength,
            output_len=caps.OutputReportByteLength,
            feature_len=caps.FeatureReportByteLength,
            product=_wstr(hid.HidD_GetProductString, h),
            manufacturer=_wstr(hid.HidD_GetManufacturerString, h))
    finally:
        k32.CloseHandle(h)


def enumerate_interfaces() -> list[HidInterface]:
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if _bad(hdev):
        raise HidError(f"SetupDiGetClassDevsW 失败 err={ctypes.get_last_error()}")
    out: list[HidInterface] = []
    cb = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    try:
        i = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    hdev, None, ctypes.byref(guid), i, ctypes.byref(data)):
                break
            i += 1
            need = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(data), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            struct.pack_into("I", buf, 0, cb)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(data), buf, need.value, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            item = _probe(path)
            if item is not None:
                out.append(item)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


# --------------------------------------------------------------------------
# 设备
# --------------------------------------------------------------------------
def pad(data: bytes, n: int) -> bytes:
    return (bytes(data) + bytes(n))[:n]


class HidDevice:
    """打开一个 HID 接口。

    write=True  读写句柄（需要发命令）；系统独占的集合会自动降级为 access=0
                （只能读属性 / Feature Report，不能收发）。
    """

    def __init__(self, iface: HidInterface, write: bool = True):
        self.iface = iface
        self._rh = self._wh = None
        self._event = None
        self._ppd = ctypes.c_void_p()
        self.caps = HIDP_CAPS()

        access = (GENERIC_READ | GENERIC_WRITE) if write else GENERIC_READ
        if write and not iface.reserved:
            self._wh = _open(iface.path, access)
        elif not write:
            self._wh = _open(iface.path, GENERIC_READ)
        self.can_io = self._wh is not None
        if self._wh is None:                      # 独占集合 / 权限不足
            self._wh = _open(iface.path, 0)
        if self._wh is None:
            raise HidError(f"无法打开 {iface.vid_pid} {iface.usage_page:04X}："
                           f"err={ctypes.get_last_error()}")
        if self.can_io and iface.input_len:
            self._rh = _open(iface.path, GENERIC_READ | GENERIC_WRITE,
                             FILE_FLAG_OVERLAPPED) or \
                _open(iface.path, GENERIC_READ, FILE_FLAG_OVERLAPPED)
            self._event = k32.CreateEventW(None, True, False, None)
        if hid.HidD_GetPreparsedData(self._wh, ctypes.byref(self._ppd)):
            hid.HidP_GetCaps(self._ppd, ctypes.byref(self.caps))

    # ---- 生命周期 ------------------------------------------------------
    def close(self) -> None:
        if self._ppd:
            hid.HidD_FreePreparsedData(self._ppd)
            self._ppd = ctypes.c_void_p()
        for h in (self._rh, self._wh):
            if h:
                k32.CloseHandle(h)
        if self._event:
            k32.CloseHandle(self._event)
        self._rh = self._wh = self._event = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- Output / Input ------------------------------------------------
    def write(self, data: bytes) -> None:
        """发 Output Report。data[0] 是 Report ID（无 ID 的设备填 0）。"""
        n = self.iface.output_len
        if not n or not self.can_io:
            raise HidError("该接口不能发送 Output Report")
        buf = ctypes.create_string_buffer(pad(data, n), n)
        wrote = wintypes.DWORD(0)
        if k32.WriteFile(self._wh, buf, n, ctypes.byref(wrote), None):
            return
        err = ctypes.get_last_error()
        if hid.HidD_SetOutputReport(self._wh, buf, n):   # 部分设备只认这个
            return
        raise HidError(f"写入失败 err={err}")

    def read(self, timeout_ms: int = 200) -> Optional[bytes]:
        """读一条 Input Report；超时返回 None。"""
        if not self._rh or not self.iface.input_len:
            return None
        n = self.iface.input_len
        buf = ctypes.create_string_buffer(n)
        ov = OVERLAPPED()
        ov.hEvent = self._event
        k32.ResetEvent(self._event)
        got = wintypes.DWORD(0)
        if not k32.ReadFile(self._rh, buf, n, None, ctypes.byref(ov)):
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise HidError(f"读取失败 err={err}")
            if k32.WaitForSingleObject(self._event, timeout_ms) != WAIT_OBJECT_0:
                k32.CancelIoEx(self._rh, ctypes.byref(ov))
        # 取消后也要等 I/O 真正结束，缓冲区和 OVERLAPPED 才能释放
        if k32.GetOverlappedResult(self._rh, ctypes.byref(ov),
                                   ctypes.byref(got), True):
            return buf.raw[:got.value]
        err = ctypes.get_last_error()
        if err == ERROR_OPERATION_ABORTED:
            return None
        raise HidError(f"读取失败 err={err}")

    def drain(self, max_reports: int = 64) -> int:
        """清掉驱动里积压的旧报告。"""
        n = 0
        while n < max_reports and self.read(timeout_ms=3) is not None:
            n += 1
        return n

    def exchange(self, request: bytes, accept, timeout: float = 0.6,
                 retries: int = 1, drain: bool = True) -> Optional[bytes]:
        """发请求，收到第一条 accept(report) 为真的回复就返回；否则 None。"""
        import time
        for _ in range(max(1, retries)):
            if drain:
                self.drain()
            self.write(request)
            end = time.monotonic() + timeout
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    break
                r = self.read(timeout_ms=max(1, int(left * 1000)))
                if r and accept(r):
                    return r
        return None

    # ---- Feature -------------------------------------------------------
    def get_feature(self, report_id: int, length: Optional[int] = None) -> bytes:
        n = length or self.iface.feature_len
        buf = ctypes.create_string_buffer(n)
        buf[0] = report_id
        if not hid.HidD_GetFeature(self._wh, buf, n):
            raise HidError(f"GetFeature 失败 err={ctypes.get_last_error()}")
        return buf.raw

    def set_feature(self, data: bytes) -> None:
        n = self.iface.feature_len or len(data)
        buf = ctypes.create_string_buffer(pad(data, n), n)
        if not hid.HidD_SetFeature(self._wh, buf, n):
            raise HidError(f"SetFeature 失败 err={ctypes.get_last_error()}")

    # ---- 解析 ----------------------------------------------------------
    def value_caps(self, report_type: int) -> list[HIDP_VALUE_CAPS]:
        count = {HidP_Input: self.caps.NumberInputValueCaps,
                 HidP_Output: self.caps.NumberOutputValueCaps,
                 HidP_Feature: self.caps.NumberFeatureValueCaps}[report_type]
        if not count or not self._ppd:
            return []
        arr = (HIDP_VALUE_CAPS * count)()
        n = USHORT(count)
        if hid.HidP_GetValueCaps(report_type, arr, ctypes.byref(n),
                                 self._ppd) != HIDP_STATUS_SUCCESS:
            return []
        return list(arr[:n.value])

    def report_ids(self) -> dict[str, list[int]]:
        """这个接口声明的 Report ID：{"in": [...], "out": [...], "feature": [...]}。

        同时看数值字段和按钮字段（厂商接口常把整包声明成一串按钮 / 字节数组）。"""
        out: dict[str, list[int]] = {}
        for name, rt, nb in (("in", HidP_Input, self.caps.NumberInputButtonCaps),
                             ("out", HidP_Output, self.caps.NumberOutputButtonCaps),
                             ("feature", HidP_Feature, self.caps.NumberFeatureButtonCaps)):
            ids = {c.ReportID for c in self.value_caps(rt)}
            if nb and self._ppd:
                size = 72                                    # sizeof(HIDP_BUTTON_CAPS)
                buf = (ctypes.c_ubyte * (size * nb))()
                n = USHORT(nb)
                if hid.HidP_GetButtonCaps(rt, buf, ctypes.byref(n),
                                          self._ppd) == HIDP_STATUS_SUCCESS:
                    ids |= {buf[k * size + 2] for k in range(n.value)}
            if ids:
                out[name] = sorted(ids)
        return out

    def usage_value(self, report_type: int, report: bytes,
                    cap: HIDP_VALUE_CAPS) -> Optional[int]:
        val = ULONG(0)
        buf = ctypes.create_string_buffer(bytes(report), len(report))
        st = hid.HidP_GetUsageValue(report_type, cap.UsagePage,
                                    cap.LinkCollection, cap.usage,
                                    ctypes.byref(val), self._ppd, buf,
                                    len(report))
        return val.value if st == HIDP_STATUS_SUCCESS else None
