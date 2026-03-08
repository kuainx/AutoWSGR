# UI 控制层架构文档

## 概述

`autowsgr/ui/` 包实现游戏全部页面的识别、状态查询与导航操作。
采用 **一页面一控制器** 模式，每个游戏页面对应一个 Python 模块。

### 三层职责

| 层级 | 模块 | 职责 |
|------|------|------|
| **基础设施** | `page.py` | 页面注册中心、导航验证 (`wait_for_page` / `wait_leave_page`) |
| **拓扑声明** | `navigation.py` | 导航树定义、路径查找 (BFS) |
| **页面控制器** | `main_page.py` 等 | 各页面的识别、状态查询、操作动作 |

---

## 导航树

```
主页面 (MainPage) ← ROOT
├── 地图页面 (MapPage)                  ← 点击「出征」(0.9375, 0.8889)
│   ├── [面板切换] 出征/演习/远征/战役/决战 ← MapPanel enum
│   └── 出征准备 (BattlePreparationPage) ← 点击地图节点
│       └── → 浴室 (BathPage)           ← 跨级: 右上角 🔧 (0.875, 0.037)
│
├── 任务页面 (MissionPage)              ← 点击「任务」(0.6833, 0.8889)
│
├── 后院页面 (BackyardPage)             ← 点击主页图标 🏛 (0.0469, 0.1481)
│   ├── 浴室 (BathPage)                ← 点击 (0.3125, 0.3704)
│   │   └── 选择修理 (ChooseRepairPage) ← 点击右上角 (0.9375, 0.0556)
│   └── 食堂 (CanteenPage)             ← 点击 (0.7292, 0.7407)
│
└── 侧边栏 (SidebarPage)               ← 点击 ≡ (0.0438, 0.8963)
    ├── 建造 (BuildPage)               ← 点击 (0.1563, 0.3704)
    │   └── [标签] 建造/解体/开发/废弃  ← BuildTab enum
    ├── 强化 (IntensifyPage)           ← 点击 (0.1563, 0.5000)
    │   └── [标签] 强化/改修/技能      ← IntensifyTab enum
    └── 好友 (FriendPage)              ← 点击 (0.1563, 0.7593)
```

### 跨级快捷通道 (Cross Edges)

| 起点 | 终点 | 说明 |
|------|------|------|
| 出征准备 | 浴室 | 右上角 🔧 修理快捷入口 |
| 浴室 | 主页面 | ◁ 可直接跳回 (跳过后院) |
| 食堂 | 主页面 | ◁ 可直接跳回 (跳过后院) |

### 页面内标签组 (Panel / Tab)

标签组成员共享同一页面识别签名，通过控制器的 `switch_panel()` / `switch_tab()` 切换，
不作为独立页面出现在导航图中。

| 页面控制器 | 标签成员 | 切换方法 |
|-----------|---------|----------|
| `MapPage` | 出征 / 演习 / 远征 / 战役 / 决战 | `switch_panel(MapPanel.XXX)` |
| `BuildPage` | 建造 / 解体 / 开发 / 废弃 | `switch_tab(BuildTab.XXX)` |
| `IntensifyPage` | 强化 / 改修 / 技能 | `switch_tab(IntensifyTab.XXX)` |

---

## 页面控制器 — 完成状态

### ✅ 签名已采集 (可用于生产)

| 控制器 | 模块 | 签名方式 | 导航 |
|--------|------|----------|------|
| `MainPage` | `main_page.py` | 7 规则 PixelSignature | 4 目标: 出征/任务/侧边栏/主页 |
| `MapPage` | `map/page.py` | 5 面板 + OCR 地图识别 | 面板切换、章节导航、地图选择 |
| `BattlePreparationPage` | `battle/preparation.py` | 舰队+面板联合检测 | 舰队选择、面板切换、开始出征 |
| `SidebarPage` | `sidebar_page.py` | 6 规则 PixelSignature | 3 目标: 建造/强化/好友 |

### 🔧 签名待采集 (Stub — 拓扑与接口已声明)

| 控制器 | 模块 | 待采集内容 | 已声明导航 |
|--------|------|-----------|-----------|
| `MissionPage` | `mission_page.py` | 页面像素签名 | ◁ 返回主页面 |
| `BackyardPage` | `backyard_page.py` | 页面像素签名 | 浴室、食堂、◁ 返回 |
| `BathPage` | `bath_page.py` | 页面像素签名 | 选择修理、◁ 返回 |
| `CanteenPage` | `canteen_page.py` | 页面像素签名 | ◁ 返回后院 |
| `BuildPage` | `build_page.py` | 页面像素签名、标签坐标精确化 | 标签切换、◁ 返回 |
| `IntensifyPage` | `intensify_page.py` | 页面像素签名、标签坐标精确化 | 标签切换、◁ 返回 |
| `FriendPage` | `friend_page.py` | 页面像素签名 | ◁ 返回侧边栏 |

### ⬜ 未实现

以下页面在旧代码中存在，但当前缺乏足够信息，暂不创建控制器:

- `support_set_page` — 支援设置 (入口路径不确定)
- `choose_repair_page` — 选择修理 (仅在 `navigation.py` 拓扑中声明)
- `news_page` / `sign_page` — 弹窗型页面 (非常规导航树成员)

---

## 控制器设计模式

### 类结构

```python
class XxxPage:
    def __init__(self, ctrl: AndroidController) -> None:
        self._ctrl = ctrl

    # ── 页面识别 (staticmethod) ──
    @staticmethod
    def is_current_page(screen: np.ndarray) -> bool: ...

    # ── 状态查询 (staticmethod，可选) ──
    @staticmethod
    def get_xxx(screen: np.ndarray) -> ...: ...

    # ── 操作动作 (实例方法) ──
    def navigate_to(self, target: XxxTarget) -> None: ...
    def go_back(self) -> None: ...
```

### 导航验证

所有导航操作遵循：

1. **点击** — `self._ctrl.click(rx, ry)`
2. **验证** — `wait_for_page()` (确认到达) 或 `wait_leave_page()` (确认离开)
3. **超时** — 抛出 `NavigationError`

签名已采集的控制器自动启用验证。签名待采集的控制器标记 `# TODO`。

### 坐标体系

- 所有坐标为 **相对值** (0.0-1.0)
- 由旧代码 960x540 绝对坐标换算: `rx = x / 960`, `ry = y / 540`
- 分为两类:
  - **探测坐标** — 采样像素颜色用于状态检测
  - **点击坐标** — 执行操作

---

## 页面注册中心

`page.py` 维护全局注册表 `_PAGE_REGISTRY`:

```python
from autowsgr.ui import get_current_page

screen = ctrl.screenshot()
page = get_current_page(screen)  # "主页面" | "地图页面" | ... | None
```

注册在 `__init__.py` 中自动完成。新增页面只需:

1. 在控制器模块中实现 `is_current_page()`
2. 在 `__init__.py` 中 `register_page("页面名", XxxPage.is_current_page)`

---

## 导航路径查找

`navigation.py` 提供 BFS 路径查找:

```python
from autowsgr.ui.navigation import find_path, NavEdge

path: list[NavEdge] | None = find_path("主页面", "建造页面")
if path:
    for edge in path:
        print(f"{edge.source} → {edge.target}: click {edge.click}")
        # ctrl.click(*edge.click)
```

输出示例:
```
主页面 → 侧边栏: click (0.0438, 0.8963)
侧边栏 → 建造页面: click (0.1563, 0.3704)
```

---

## 旧代码 (V1) 对照

| V1 概念 | V2 对应 | 说明 |
|---------|---------|------|
| `ALL_PAGES` (23 页面) | `navigation.ALL_PAGES` (12 页面) | V2 将标签组成员作为页面内 Panel/Tab |
| `page_tree` + LCA | `NAV_GRAPH` + BFS | 有向图替代树，支持跨级边 |
| `timer.now_page` | `get_current_page(screen)` | 无状态识别，无需手动维护 |
| `goto_game_page()` | `MainPage.navigate_to()` 等 | 每个控制器独立负责验证 |
| `identify_page()` | `get_current_page()` | 遍历注册表 |
| `image_exist()` + 像素检查 | `PixelSignature` + `PixelChecker` | 纯像素方案，无模板图依赖 |
| 绝对坐标 (960x540) | 相对坐标 (0.0-1.0) | 分辨率无关 |

---

## 文件结构

```
autowsgr/ui/
├── __init__.py               # 导出 + 页面注册
├── page.py                   # 注册中心 + 导航验证
├── navigation.py             # 导航树定义 + 路径查找
├── main_page.py              # ✅ 主页面
├── map/                      # ✅ 地图页面子包
│   ├── data.py               #   数据常量 + 枚举 + OCR 解析
│   ├── page.py               #   MapPage 控制器 (核心)
│   └── ops.py                #   战役/决战/演习/远征操作
├── battle/                   # ✅ 出征准备子包
│   ├── constants.py          #   坐标/颜色常量
│   └── preparation.py        #   BattlePreparationPage 控制器
├── sidebar_page.py           # ✅ 侧边栏
├── mission_page.py           # 🔧 任务页面
├── backyard_page.py          # 🔧 后院页面
├── bath_page.py              # 🔧 浴室
├── canteen_page.py           # 🔧 食堂
├── build_page.py             # 🔧 建造 (含 4 个标签)
├── intensify_page.py         # 🔧 强化 (含 3 个标签)
└── friend_page.py            # 🔧 好友
```

✅ = 签名已采集、可用于生产
🔧 = 接口已声明、签名待采集

---

## 签名采集指南

为 stub 页面补充签名的步骤:

1. 导航到目标页面，使用 `ctrl.screenshot()` 获取截图
2. 选择 5-8 个稳定特征点 (避免动态区域)
3. 使用工具提取像素 RGB 值和相对坐标
4. 构建 `PixelSignature`，设置合适 `tolerance` (通常 30.0)
5. 替换 `is_current_page()` 实现
6. 在 `__init__.py` 中注册 (已预注册)
7. 运行测试验证

工具参考: `sig.py` (根目录) 包含已采集的签名样例。
