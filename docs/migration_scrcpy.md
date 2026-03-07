# 截图方案迁移：Airtest/minicap → scrcpy

## 1. 背景与动机

### 当前方案（Airtest + minicap）的问题

| 问题 | 详情 |
|------|------|
| **minicap 兼容性差** | Android 12 x86_64（LDPlayer 等模拟器）需要手动交叉编译 64 位 `minicap.so`，依赖 Android NDK r25c 和 24 个 AOSP 桩头文件 |
| **自定义 fork** | 项目依赖 `airtest-openwsgr`（自定义 fork），增加维护负担，PyPI 发布需同步维护 fork |
| **降级到 ADBCAP** | 当 minicap/javacap 都不可用时，Airtest 静默降级到 `adb shell screencap`（~3 fps），根本无法满足自动化需求 |
| **Airtest 重量级** | Airtest 引入大量传递依赖（poco、wda 等），本项目只用了截图+触控两项能力 |
| **安装复杂** | 用户需要修改 venv 内部的 Airtest 文件才能在特定设备上正常工作 |

### 迁移目标

- **纯 pip 安装**：`pip install autowsgr` 即可运行，无需编译 native 代码
- **Windows 首要支持**：所有依赖必须有 Windows x86_64 预编译 wheel
- **高性能截图**：≥15 fps（scrcpy H264 流解码可达 30+ fps）
- **减少依赖**：移除 Airtest，使用更轻量、更主流的库
- **PyPI 友好**：所有运行时资源可打包为 package data

## 2. 技术方案

### 2.1 新依赖栈

| 组件 | 包名 | 版本要求 | 用途 | PyPI wheel |
|------|------|----------|------|-----------|
| ADB 通信 | `adbutils` | ≥2.0 | 设备连接、shell、应用管理 | ✅ 纯 Python |
| 视频解码 | `av` (PyAV) | ≥12.0 | H264 流解码为 numpy 帧 | ✅ 预编译 (Win/Linux/macOS) |
| 图像处理 | `opencv-python` | ≥4.5 | 色彩空间转换（已有依赖） | ✅ |
| 图像处理 | `numpy` | — | ndarray 帧表示（opencv 传递依赖） | ✅ |

**移除的依赖**：`airtest-openwsgr`

### 2.2 scrcpy-server 管理

scrcpy 的截图能力依赖于运行在 Android 设备上的 `scrcpy-server`（一个 ~88KB 的 JAR 文件）。

**方案**：将 `scrcpy-server.jar` 打包在 `autowsgr/data/bin/` 目录下作为 package data。

- **许可证**：scrcpy-server 使用 Apache 2.0 许可证，允许打包分发
- **版本**：跟随 scrcpy 稳定版本（当前 v2.7）
- **大小**：~74KB，对包体积影响可忽略

### 2.3 架构设计

```
┌─────────────────────────────────────────────────────┐
│                  AndroidController (ABC)             │
│  screenshot() / click() / swipe() / key_event() ... │
└──────────────────────┬──────────────────────────────┘
                       │ implements
┌──────────────────────▼──────────────────────────────┐
│                  ScrcpyController                    │
│                                                      │
│  ┌──────────────┐   ┌─────────────────────────────┐ │
│  │  adbutils    │   │  scrcpy video stream        │ │
│  │  AdbDevice   │   │                             │ │
│  │              │   │  scrcpy-server (on device)   │ │
│  │ • shell()    │   │       ↓ H264 stream          │ │
│  │ • click()    │   │  av.CodecContext (decode)    │ │
│  │ • keyevent() │   │       ↓ numpy frame          │ │
│  │ • push()     │   │  _last_frame (thread-safe)   │ │
│  └──────────────┘   └─────────────────────────────┘ │
│                                                      │
│  screenshot() → return _last_frame                   │
└──────────────────────────────────────────────────────┘
```

### 2.4 ScrcpyController 关键设计

#### 连接流程

```python
def connect():
    # 1. 通过 adbutils 连接设备
    device = adbutils.adb.device(serial=serial)

    # 2. 推送 scrcpy-server.jar 到设备
    device.push(jar_path, "/data/local/tmp/scrcpy-server.jar")

    # 3. 启动 scrcpy-server（后台 shell 流）
    server_stream = device.shell([
        "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
        "app_process", "/",
        "com.genymobile.scrcpy.Server",
        "2.7",       # 协议版本
        "log_level=info",
        "tunnel_forward=true",
        "video=true",
        "audio=false",
        "control=false",
        "max_size=0",
        "max_fps=30",
        "video_codec=h264",
        "send_device_meta=true",
        "send_frame_meta=false",
    ], stream=True)

    # 4. 连接 video socket
    video_socket = device.create_connection(
        adbutils.Network.LOCAL_ABSTRACT, "scrcpy"
    )

    # 5. 读取设备元数据（64 字节设备名 + 4 字节分辨率）
    dummy = video_socket.recv(1)
    device_name = video_socket.recv(64)
    resolution = struct.unpack(">HH", video_socket.recv(4))

    # 6. 启动后台解码线程
    threading.Thread(target=_stream_loop, daemon=True).start()
```

#### 截图实现

```python
def _stream_loop():
    """后台解码线程：持续从 H264 流解码帧。"""
    codec = av.CodecContext.create("h264", "r")
    while self._alive:
        raw = video_socket.recv(65536)
        for packet in codec.parse(raw):
            for frame in codec.decode(packet):
                # frame.to_ndarray() 直接得到 numpy 数组
                self._last_frame = frame.to_ndarray(format="rgb24")

def screenshot() -> np.ndarray:
    """返回最新一帧截图（零拷贝，由后台线程持续更新）。"""
    return self._last_frame
```

#### 触控输入

使用 `adbutils.AdbDevice` 的内置方法或 `adb shell input` 命令：

```python
def click(x: float, y: float):
    px, py = int(x * width), int(y * height)
    device.shell(f"input tap {px} {py}")

def swipe(x1, y1, x2, y2, duration=0.5):
    device.shell(f"input swipe {px1} {py1} {px2} {py2} {ms}")
```

### 2.5 与 ADBController 的对比

| 特性 | ADBController (Airtest) | ScrcpyController |
|------|------------------------|-----------------|
| 截图方式 | minicap/javacap/adbcap | scrcpy H264 流 |
| 截图性能 | 30 fps (minicap) / 3 fps (adbcap) | 30+ fps |
| 设备兼容性 | 需要正确的 minicap.so | scrcpy 支持 Android 5.0+ |
| 触控方式 | adb shell input | adb shell input（相同） |
| 安装复杂度 | 需编译 minicap.so | pip install 即可 |
| Windows 预编译 wheel | ❌ (airtest 需要编译) | ✅ (adbutils 纯 Python, av 有 wheel) |
| 额外二进制 | minicap + minicap.so (设备端) | scrcpy-server.jar (88KB, 自动推送) |

## 3. 迁移影响

### 3.1 直接影响的文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `autowsgr/emulator/controller/scrcpy.py` | **新增** | ScrcpyController 实现 |
| `autowsgr/emulator/controller/__init__.py` | 修改 | 导出 ScrcpyController |
| `autowsgr/emulator/__init__.py` | 修改 | 导出 ScrcpyController |
| `autowsgr/emulator/controller/adb.py` | 保留 | 保留 ADBController 作为备用方案 |
| `autowsgr/scheduler/launcher.py` | 修改 | 默认使用 ScrcpyController |
| `pyproject.toml` | 修改 | 更新依赖 |
| `autowsgr/data/bin/scrcpy-server.jar` | **新增** | 打包 scrcpy-server |
| `autowsgr/emulator/os_control/linux.py` | 修改 | 移除 airtest ADB 依赖 |
| `autowsgr/infra/logger.py` | 修改 | 移除 airtest 日志抑制配置 |

### 3.2 不影响的模块

- `autowsgr/combat/` — 只通过 `AndroidController` 接口交互
- `autowsgr/vision/` — 只接收 numpy 数组
- `autowsgr/context/` — 只持有 `AndroidController` 引用
- `autowsgr/image_resources/` — 与截图方案无关

### 3.3 旧方案保留

`ADBController`（Airtest 方案）保留在代码中但不再作为默认选项。
`airtest-openwsgr` 移为可选依赖 (`pip install autowsgr[airtest]`)，便于已有用户平滑过渡。

## 4. PyPI 发布兼容性

| 检查项 | 状态 |
|--------|------|
| 所有运行时依赖有 Windows wheel | ✅ adbutils (纯 Python), av (预编译), opencv-python (预编译) |
| 无需编译 native 代码 | ✅ 移除 minicap 编译需求 |
| scrcpy-server.jar 可作为 package data | ✅ 88KB, Apache 2.0 许可证 |
| Python 3.12+ 兼容 | ✅ 所有新依赖支持 |
| 无平台特定的二进制分发 | ✅ 纯 Python + 预编译 wheel |

## 5. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| scrcpy-server 版本升级导致协议不兼容 | 锁定 server 版本，协议版本号在握手时校验 |
| H264 解码延迟 | PyAV 使用 FFmpeg 硬件加速路径，实测延迟 <10ms |
| adbutils 2.x API 变更 | 锁定主版本 `>=2.0,<3.0` |
| 设备首次连接需推送 JAR | 仅首次推送，后续检查已存在则跳过 |
| 旧版 Android 的 scrcpy 兼容性 | scrcpy 支持 Android 5.0+，覆盖所有目标设备 |
