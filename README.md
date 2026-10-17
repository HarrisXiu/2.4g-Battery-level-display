# 外设电量

Windows 上查看 **2.4G 无线键鼠电量**的小工具：面板 + 托盘 + 命令行。

- **不需要厂商驱动**：Cherry Utility、罗技 G HUB、雷柏驱动都不用装、不用开，直接和接收器的 HID 接口通信。
- **单文件便携 exe**：[下载](https://github.com/HarrisXiu/2.4g-Battery-level-display/releases/latest)后双击即用，不需要装 Python；配置和插件都放在 exe 旁边，整个文件夹拷到哪都能用。
- **零第三方依赖**：纯 Python 标准库 + ctypes 调系统 DLL。
- **可扩展**：一条 JSON 或一个 Python 插件就能加新品牌 / 新型号，也可以[让 AI 帮你写插件](#用-ai-开发插件增加品牌或型号)。
- 不联网、不写日志、不上传任何信息。

## 已支持的设备

| 品牌 | 协议 | 状态 |
|---|---|---|
| **Cherry 键盘** | 私有帧：命令 `0x1A`，电量在回复第 8 字节（接口 `FF1C`） | ✅ 实测：MX 8.3 Wireless |
| **罗技** 鼠标 / 键盘 | HID++ 2.0：`0x1004` 统一电池 → `0x1000` 电池状态 → `0x1001` 电压估算 | ✅ 实测：PRO X 2（LIGHTSPEED）；一个接收器挂多台设备会各显示一张卡片 |
| **雷柏** 鼠标 | VT 系列协议：鼠标使用时约每 3 秒推送的用户数据报告 `0x07`，第 8 字节是电量 | ✅ 实测：VT3S Air Max；同协议的 VT0 ~ VT9 各代、ESM6xx 共 77 个型号按型号表识别 |
| **ATK** 鼠标 | Report `0x08`：协议 2（接口 `FF05`），后备协议 1（接口 `FF02`） | 协议 2 取自公开资料；协议 1 ⚠️ 未实测 |
| **VGN / VXE** 鼠标 | 与 ATK 同平台的协议 1 / 2 | ⚠️ 未实测 |
| 任意设备 | 兜底：设备按 HID 标准声明了电量字段（Battery Strength）就能读 | 通用 |

- 只显示检测到的设备，没插的接收器不会出现。
- 未在真机验证过的设备，界面上会标「未实测」。
- 设备休眠暂时读不到时，**沿用上次读数**并标「休眠中」，不会一会儿是数字一会儿是 `--`。

## 下载

到 **[Releases](https://github.com/HarrisXiu/2.4g-Battery-level-display/releases/latest)** 下载最新版：

| 文件 | 说明 |
|---|---|
| `BatteryMonitor-vX.Y.Z-windows-x64.zip`（推荐） | 便携文件夹：`外设电量.exe` + `devices.json` + `plugins/`，解压到任意位置，双击 `外设电量.exe` 即用 |
| `BatteryMonitor-vX.Y.Z.exe` | 只有程序本体，可改名为 `外设电量.exe` |

系统要求 Windows 10 / 11（64 位），不需要安装 Python。exe 没有数字签名，首次运行时 SmartScreen 若提示「已保护你的电脑」，
点「更多信息 → 仍要运行」即可。也可以[从源码打包](#从源码打包-exe)。

## 使用

| 命令 | 作用 |
|---|---|
| `外设电量.exe` | 打开面板 |
| `外设电量.exe --tray` | 托盘常驻 |
| `外设电量.exe --once [--json]` | 读一次，打印后退出 |
| `外设电量.exe --list` | 列出所有 HID 接口：VID:PID、usage page、报告长度、Report ID |
| `外设电量.exe --sniff VID:PID [--seconds 30]` | 监听某个设备上报的报文（摸新协议用） |
| `外设电量.exe --autostart on\|off\|status` | 开机自启 |
| `外设电量.exe --quit` | 让后台托盘退出 |

从源码运行时把 `外设电量.exe` 换成 `python main.py`（需要 Python 3.10+，自带 tkinter 即可）。

> exe 是窗口程序（不弹黑窗）。在 cmd / PowerShell 里直接运行 `--once`、`--list` 时，输出会接回当前控制台，
> 但提示符可能先回来；想要干净的输出用 `外设电量.exe --list | more`，或用源码的 `python main.py --list`。

### 面板

- 每台设备一张卡片：设备图标、型号、环形电量表、电量状态，以及「充电中 / 休眠中 / 未实测」标签。
- **拖动窗口边框可改大小**：宽度够就两三列并排，窄了自动变成一列；卡片多时中间区域用滚轮滚动，设置栏始终在底部。窗口大小会记住。
- 设置栏：刷新间隔（30 秒 ~ 30 分钟）、自动刷新、开机自启、启动 / 退出托盘。

### 托盘

- 每台设备一个图标：**上面是电量数字**（≥60 绿 / 30–59 黄 / <30 红），**下面是设备类型小图标**（扁宽带点阵 = 键盘，窄高带中缝 = 鼠标），配色跟随任务栏的深浅主题。
- 鼠标悬停显示设备名和电量；左键立即刷新；双击或右键菜单「打开面板」。
- 右键菜单：打开面板 / 立即刷新 / 开机自启 / 退出。
- 开机自启是「启动」文件夹里的快捷方式，任务管理器 →「启动」标签里可见、可禁用；程序**不会**自己改这个设置。

## 加新设备

三种方式，从简单到灵活。`devices.json` 和 `plugins/` 都放在 **exe 旁边**（源码运行时是项目目录），
加完重新打开程序即可，不用重新打包。

优先级：`plugins` → `devices.json` → 内置品牌驱动 → 通用兜底。同一个 VID:PID 只交给第一个认领它的驱动，
所以插件也可以用来覆盖内置驱动。

### 1. `devices.json`：不写代码

适合「发一包请求、电量在回复的某个字节」这种简单协议：

```json
{
  "devices": [{
    "name": "我的鼠标", "brand": "某品牌", "kind": "mouse",
    "vid": "373B", "pid": "1216",
    "usage_page": "FF05",
    "mode": "output",
    "report_length": 64,
    "request": "08 7D 72 02 00 01 07 01",
    "expect": {"1": "72", "5": "07"},
    "level_offset": 7, "level_max": 100,
    "verified": true
  }]
}
```

| 字段 | 含义 |
|---|---|
| `vid` / `pid` | 十六进制字符串或数字；`pid` 可省略（同 VID 全认） |
| `usage_page` | 用哪个接口，`--list` 里看；省略 = 第一个能收发的 |
| `mode` | `output`：写 Output Report、等 Input 回复；`feature`：SetFeature 后 GetFeature |
| `request` | 请求报文（十六进制），**第一个字节是 Report ID**，不足的长度自动补 0 |
| `expect` | 回复过滤：`{下标: 期望值}`，只认符合的那条（防止收到别的软件的回复） |
| `level_offset` | 电量字节的下标（从 Report ID 算第 0 个） |
| 可选 | `scale`（电量 = 字节 × scale）、`level_max`、`charging_offset`、`retries`、`wait_ms`、`report_length` |

### 2. `plugins/*.py`：写一个 Python 驱动

协议复杂（多步查询、校验和、设备主动推送……）时用插件。把 `.py` 文件丢进 `plugins/` 即自动加载，
模板和写法见 [plugins/README.md](plugins/README.md)。内置驱动 `drivers/*.py` 也是同样的写法，可以直接参考。

### 3. 内置驱动

在 `drivers/` 里加文件，并在 `drivers/__init__.py` 的 `load_all()` 里登记模块名，然后重新打包。

## 用 AI 开发插件，增加品牌或型号

自己不想读协议、写代码？可以把下面这段提示词交给一个 **AI Agent**，让它在你的电脑上把新设备摸清楚并写成插件。
本项目里雷柏的支持就是这么做出来的：AI 从雷柏官方网页驱动的 JavaScript 里读出了协议和 77 个型号的对照表。

**需要的是「Agent」，不是聊天窗口**：它要能在你电脑上执行命令、读写文件——枚举 HID 接口、收发报文、做对照实验，
每一步都得真跑。Claude Code、Cursor、WorkBuddy / CodeBuddy 这类都可以。

### 步骤

1. 用**源码版**（clone 本仓库），在项目目录里打开 AI Agent。
2. 插上新设备的接收器，设备开机。如果装了厂商软件，记下它显示的电量，方便核对。
3. 复制 [PROMPT.md](PROMPT.md) 里「=== 提示词开始 ===」到「=== 提示词结束 ===」之间的内容，**先填好最上面「我的设备」那一段**，发给 Agent。
4. Agent 会：用 `--list` 认清接口 → 按优先级找协议（厂商网页驱动 → 开源项目 → 抓官方软件的报文）→ 只用只读命令做对照实验验证 → 写成 `plugins/<品牌>_<型号>.py` → 自测。
5. 让它告诉你读到的电量和官方显示是否一致，以及协议是从哪来的。
6. 用 exe 的话，把生成的插件文件复制到 exe 旁边的 `plugins/` 文件夹即可。

提示词里已经写好了**安全要求**（只发读取命令、绝不盲发 / 爆破命令、不碰固件升级接口）、
**无驱动要求**（最终插件不能依赖厂商软件运行）、验证方法，以及做 Cherry / 罗技 / 雷柏时踩过的坑。

<details>
<summary><b>点开查看给 AI 的提示词全文</b>（与 PROMPT.md 相同，复制「提示词开始」到「提示词结束」之间的内容）</summary>

=== 提示词开始 ===

#### 我的设备（请先填写）

- 品牌 / 型号：＿＿＿＿（例：雷柏 VT9 PRO、达尔优 A980）
- 设备类型：鼠标 / 键盘 / 耳机 / 其他
- 连接方式：2.4G 接收器 / 有线 / 蓝牙
- VID:PID（不知道可以不填，你来查）：＿＿＿＿
- 厂商有没有**网页驱动**（浏览器里就能改设置的那种）？网址：＿＿＿＿
- 厂商驱动软件（如果装了）：＿＿＿＿；它现在显示的电量是：＿＿%（用来核对你读出来的数对不对）

#### 你的任务

这是一个 Windows 上读取外设电量的工具（项目目录就是当前目录，Python + ctypes，零第三方依赖）。
请为上面这台设备写一个**插件**，让面板、托盘和 `python main.py --once` 都能显示它的电量。

开工前先读：`README.md`、`plugins/README.md`、`drivers/__init__.py`（Driver / Reading / register 接口），
再看一个和你的情况最像的现成驱动当参考：
- `drivers/cherry.py`：发一条请求、按命令字节过滤回复（请求-应答型）
- `drivers/logitech.py`：先查特性索引再调函数（多级协议、多设备挂一个接收器）
- `drivers/rapoo.py`：设备没有查询命令，只会主动推送 → 常驻线程监听、缓存最近一份（推送型）
- `drivers/declarative.py` + `devices.json`：简单的「发一包、取某字节」可以不写代码

#### 硬性要求

1. **无驱动**：最终插件不能依赖厂商软件在运行，直接通过 `hidraw.py` 和接收器的 HID 接口通信。
   厂商软件 / 网页驱动只能拿来**查协议、对照结果**。
2. **只读、安全**：
   - 只发送确认是「读取 / 查询」的命令；**绝对不要盲发、遍历、爆破命令**——
     未知命令可能改掉 DPI、灯效、按键映射、配对关系，甚至进入固件升级模式把设备刷坏。
   - 不碰标着 update / firmware / bootloader / DFU 的接口和命令。
   - 能纯监听就纯监听，能不发就不发。
3. **零第三方依赖**：只用标准库和项目里现成的 `hidraw.py`，不要引入 hidapi / pywinusb 等。
4. **代码放在 `plugins/<品牌>_<型号>.py`**（或者一条 `devices.json`）。除非确有必要，不要改 core / panel / tray。
5. 只有**在真机上验证过**才能写 `verified = True`；同一协议族里没实测的型号写 `verified = False`（界面会标「未实测」）。

#### 工作流程

##### 第 1 步：认清设备

```bash
python main.py --list            # 所有 HID 接口：VID:PID、usage page、各报告长度、Report ID、哪些是系统独占
python main.py --once            # 看现有驱动 / 通用兜底能不能直接读出来
```

- usage page ≥ `0xFF00` 的是厂商自定义接口，协议几乎都在这里。
- `--list` 末尾方括号里是每个接口声明的 **Report ID**（代码里用 `hidraw.HidDevice.report_ids()`）。
  报告长度含 Report ID 那 1 个字节；Report ID 为 0 表示这个接口不用 ID。
- 先确认设备有没有按 HID 标准声明电量（Usage Page `0x06` / Usage `0x20`，或 `0x85` 页）——
  有的话通用驱动已经能读，不用写插件。

##### 第 2 步：找协议（按这个优先级）

**A. 厂商网页驱动（最推荐，雷柏就是这么做出来的）**
很多品牌有「网页驱动 / Web Hub」，它用浏览器的 WebHID 和设备通信，**整套协议就写在网站的 JavaScript 里**：
1. 打开网页驱动首页，用浏览器开发者工具或 `performance.getEntriesByType('resource')` 找出主 JS 包；
2. `fetch` 下来在里面搜：VID / PID 的**十进制**写法（如 `vendorId:9390`、`productId:[18082,5282]`）、
   `battery`、`batPercent`、`电量`、`sendReport`、`sendFeatureReport`、`receiveFeatureReport`、`inputreport`；
3. 顺着设备定义找到它用的 `driver` 名称和对应的类，弄清：用哪个接口（usagePage/usage）、
   Report ID、帧格式、命令号、回复从哪读（Input 还是 Feature）、电量在第几个字节、充电状态怎么表示；
4. 设备定义里常有**型号 ↔ PID 对照表**，一并收录，能让同协议的一整个系列都识别出型号名。

**B. 开源项目**：OpenRGB、Solaar（罗技）、libratbag / piper、Linux 内核 `hid-*` 驱动、
GitHub 上搜 `VID 电量 hid` 之类的关键词。

**C. 抓官方软件的报文**：让厂商软件运行起来，同时
```bash
python main.py --sniff VID:PID --seconds 30
```
Windows 会把设备的 Input Report 广播给所有打开它的句柄，所以能看到**官方软件收到的回复**
（看不到它发出去的请求）。从回复反推请求：Cherry 的协议就是这样推出来的——
回复里的校验和 = 命令 + 参数之和，于是请求就是「同样的帧头、载荷清零」。
如果实在需要看请求，再请用户自己装 USBPcap + Wireshark 抓包。

##### 第 3 步：验证（必须做，不能只看一次读数就下结论）

1. **对照实验**：同样的时间窗口，「不发请求只监听」和「发请求后监听」各做几轮，
   证明回复确实是你的请求触发的，而不是别的软件的流量或者设备的定时推送。
2. **每次都用新句柄，先 drain**：驱动里会积压旧报告，拿到「0 毫秒就回复」时要警惕是旧数据。
3. 连续读十几次结果一致；在厂商软件**开着**和**关着**两种情况下都能读。
4. 和厂商软件 / 设备指示灯显示的电量核对，告诉我你读到的数和官方显示的数。
5. 设备休眠 / 关机时要返回带说明的失败读数（`self.fail(...)`），不能卡住、不能抛异常拖垮扫描；
   扫描一次的耗时尽量 < 1 秒（推送型设备用常驻监听，见 `drivers/rapoo.py`）。

##### 第 4 步：写插件

模板见 `plugins/README.md`，要点：
- `match(ifaces)` 认准 VID（必要时加 PID / usage page），不要误认别的设备；
- 回复一定要按特征过滤（命令字节、Report ID、设备索引……），只接受自己那条；
- 文件开头用注释写清**协议摘要**：接口、Report ID、请求帧、回复里各字节含义、数据来源（网页驱动 / 抓包 / 开源项目）；
- `Reading` 填好 `name`（尽量是具体型号）、`kind`、`level`、`charging`、`source`、`verified`。

##### 第 5 步：交付前自测

```bash
python main.py --once           # 连跑几次
python main.py --once --json    # 看 key / 字段是否合理
python main.py                  # 面板里卡片正常
python main.py --tray --debug   # 托盘图标正常（Ctrl+C 或 python main.py --quit 退出）
```
最后告诉我：协议从哪来、怎么验证的、读到的电量和官方显示是否一致、还有什么没验证到。

#### 已知的坑（前人踩过的）

- **回复是广播的**：官方软件也在轮询时，你会收到它的回复，必须按命令字节等特征过滤。
- **迟到的回复会串号**：超时后上一条请求的回复可能晚到，被当成下一条的答案。
  能带序号 / 软件 ID 的协议，每个请求换一个（罗技 HID++ 就因此读出过「15%、充电中」这种错值）。
- **特性索引 / 偏移别想当然**：罗技 HID++ 的特性索引在回复第 4 字节，不是第 6 字节；
  `0x1004` 统一电池要调函数 1（getStatus），函数 0 返回的是能力描述。
- **Feature 报告的第一个字节不一定是 Report ID**：雷柏的回复首字节是应答码（1=成功、2=忙）。
- **有的设备没有查询命令**，只在被使用时周期推送、静止一会儿就停（雷柏 VT 系列）→ 常驻监听 + 缓存。
- **休眠的设备**第一个包可能只是把它唤醒：已知设备给长一点的超时并重试。
- **系统独占的集合**（鼠标 / 键盘的标准接口）不能以读写方式打开，`hidraw` 会自动降级为只读属性。
- 不要在同一个同步句柄上并发「阻塞读 + 写」，`hidraw.HidDevice` 已经用独立的重叠读句柄处理好了，直接用它。

=== 提示词结束 ===

</details>

做出来的插件如果好用，欢迎提 PR 合进内置驱动。

## 配置

`config.json`（自动生成，在 exe 旁边）：

| 键 | 含义 |
|---|---|
| `interval` | 刷新间隔（秒），面板里可改 |
| `window` | 面板窗口大小，拖动后自动记住 |
| `hidden` | 不想显示的设备 key，如 `["046D:C54D#1"]`（key 用 `--once --json` 查看） |
| `names` | 自定义显示名，如 `{"24AE:14A2": "我的雷柏"}` |

## 从源码打包 exe

```bash
pip install pyinstaller      # 只有打包时需要
python build.py              # 产物在 release/：外设电量.exe + devices.json + plugins/
```

单文件约 12 MB。打包前先退出正在运行的托盘 / 面板（否则 exe 被占用无法覆盖）。
PyInstaller 单文件 exe 偶尔会被杀毒软件误报，可自行加信任；每次启动要先解压，会慢一两秒。

## 项目结构

| 文件 | 作用 |
|---|---|
| `main.py` | 入口：面板 / 托盘 / 命令行 |
| `hidraw.py` | ctypes HID 底层：枚举接口、Report ID、读写 Output / Feature / Input 报告 |
| `core.py` | 扫描：按 VID:PID 分组交给驱动；设备休眠时沿用旧读数 |
| `drivers/__init__.py` | 驱动注册接口：`Driver`、`Reading`、`@register`、插件与 `devices.json` 加载 |
| `drivers/*.py` | 各品牌驱动：`cherry`、`logitech`、`rapoo`、`atk`、`vgn`、`generic`（标准电量字段兜底）、`declarative`（devices.json） |
| `panel.py` / `aa.py` | 面板；`aa.py` 负责抗锯齿绘制圆角、圆环、开关 |
| `tray.py` | 托盘：数字图标、菜单、定时刷新 |
| `config.py` / `paths.py` | 配置与开机自启；源码 / exe 两种运行方式的路径 |
| `build.py` | 打包脚本（顺带生成图标） |
| `PROMPT.md` | 给 AI 的插件开发提示词 |

## 说明

- 私有协议来自实机抓包、厂商网页驱动和公开资料，仅供个人使用。
- 和厂商软件同时运行也不冲突：回复按命令字节过滤，不会读串。
- 罗技接收器和 G HUB 共用 HID++ 通道，一般没问题；雷柏鼠标静止时不上报，刚启动时动一下鼠标，几秒后就会出现电量。

## 许可

[MIT](LICENSE)
