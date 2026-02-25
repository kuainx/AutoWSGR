# UI 模块 API 文档

## 概览

`autowsgr/ui/` 模块负责游戏界面的识别、导航与操作。整体分为三层：

| 层次 | 模块 | 职责 |
|------|------|------|
| **基础设施** | `page.py` / `navigation.py` / `tabbed_page.py` | 导航原语、路径查找、标签页识别 |
| **页面控制器** | 各 `*_page.py` / `battle/` / `map/` / 等 | 封装具体页面的识别、查询与操作 |
| **导航图** | `navigation.py` `NAV_GRAPH` | 声明页面间的有向边与 BFS 路径查找 |

---

## 一、基础设施层

### 1.1 `page.py` — 导航原语与页面注册

#### 异常

| 类 | 说明 |
|----|------|
| `NavigationError` | 超时未到达目标页面，或重试耗尽 |

#### 配置

```python
@dataclass(frozen=True)
class NavConfig:
    max_retries: int = 2      # 点击重试最大次数
    retry_delay: float = 1.0  # 两次点击间等待 (秒)
    timeout: float = 5.0      # 每轮验证超时 (秒)
    interval: float = 0.5     # 截图轮询间隔 (秒)
    handle_overlays: bool = True  # 是否自动处理浮层

DEFAULT_NAV_CONFIG = NavConfig()
```

#### 页面注册

| 函数 | 签名 | 说明 |
|------|------|------|
| `register_page` | `(name, checker) → None` | 注册页面识别函数 |
| `get_current_page` | `(screen) → str \| None` | 遍历注册表识别当前截图 |
| `get_registered_pages` | `() → list[str]` | 返回所有已注册页面名称 |

#### 导航验证

| 函数 | 签名 | 说明 |
|------|------|------|
| `wait_for_page` | `(ctrl, checker, *, timeout, interval, handle_overlays, source, target) → ndarray` | 反复截图直到 `checker` 为 `True`，含浮层消除 |
| `wait_leave_page` | `(ctrl, checker, *, timeout, interval, handle_overlays, source, target) → ndarray` | 反复截图直到 `checker` 为 `False`（已离开） |

#### 带重试的导航（推荐 API）

| 函数 | 签名 | 说明 |
|------|------|------|
| `click_and_wait_for_page` | `(ctrl, click_coord, checker, *, source, target, config) → ndarray` | 点击 + 等待到达目标页面，内置重试 |
| `click_and_wait_leave_page` | `(ctrl, click_coord, checker, *, source, target, config) → ndarray` | 点击 + 等待离开当前页面，内置重试 |

#### 确认弹窗

| 函数 | 签名 | 说明 |
|------|------|------|
| `confirm_operation` | `(ctrl, *, must_confirm, delay, confidence, timeout) → bool` | 等待并点击弹出的确认按钮；`must_confirm=True` 时超时抛异常 |

---

### 1.2 `navigation.py` — 导航图与路径查找

#### 数据结构

```python
@dataclass(frozen=True)
class NavEdge:
    source: PageName       # 出发页面
    target: PageName       # 到达页面
    action: Callable[[AndroidController], None]  # 执行导航的函数
    description: str = ""  # 人类可读描述
```

#### 导航图 `NAV_GRAPH`

声明的有向边（部分列举）：

| 出发 | 目标 | 说明 |
|------|------|------|
| `MAIN` | `MAP` | 主页面 → 地图 |
| `MAIN` | `MISSION` | 主页面 → 任务 |
| `MAIN` | `BACKYARD` | 主页面 → 后院 |
| `MAIN` | `SIDEBAR` | 主页面 → 侧边栏 |
| `MAIN` | `EVENT_MAP` | 主页面 → 活动 |
| `MAP` | `MAIN` | 地图 → 主页面 |
| `MAP` | `DECISIVE_BATTLE` | 地图 → 决战 |
| `BATTLE_PREP` | `MAP` | 出征准备 → 地图 |
| `BACKYARD` | `BATH` / `CANTEEN` | 后院 → 浴室/食堂 |
| `SIDEBAR` | `BUILD` / `INTENSIFY` / `FRIEND` | 侧边栏 → 建造/强化/好友 |
| `DECISIVE_BATTLE` | `MAIN` | 决战 → 主页面（跨级） |

#### 路径查找

| 函数 | 签名 | 说明 |
|------|------|------|
| `find_path` | `(source: str, target: str) → list[NavEdge] \| None` | BFS 最短路径；`source==target` 返回 `[]`；不可达返回 `None` |

---

### 1.3 `tabbed_page.py` — 标签页统一检测层

地图、建造、强化、任务、好友五种页面共享同一顶部标签栏，由此模块统一检测。

#### 枚举

```python
class TabbedPageType(enum.Enum):
    MAP       # 地图 (5 标签)
    BUILD     # 建造 (4 标签)
    INTENSIFY # 强化 (3 标签)
    MISSION   # 任务 (5 标签)
    FRIEND    # 好友 (4 标签)
```

#### 公共函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `is_tabbed_page` | `(screen) → bool` | 判断是否为标签页（1 蓝 + 其余暗） |
| `get_active_tab_index` | `(screen) → int \| None` | 获取激活标签索引 (0–4) |
| `identify_page_type` | `(screen) → TabbedPageType \| None` | 通过标签栏模板匹配识别页面类型 |
| `make_tab_checker` | `(page_type, tab_index) → Callable` | 创建同时验证页面类型和标签索引的 checker |
| `make_page_checker` | `(page_type) → Callable` | 创建仅验证页面类型的 checker |

---

## 二、页面控制器

所有页面控制器遵循统一设计约定：
- **`is_current_page(screen)`** — `staticmethod`，截图识别
- **`get_*` / `has_*`** — `staticmethod`，状态查询，不执行副作用
- **`navigate_to()` / `go_back()` / `close()`** — 实例方法，执行导航
- **操作方法** — 实例方法，执行页面内操作

---

### 2.1 `MainPage` — 主页面（母港）

> 路径：`autowsgr/ui/main_page/controller.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 识别主页面（含新闻/签到/预约浮层） |
| `is_base_page(screen)` | `staticmethod → bool` | 仅识别干净主页面（无浮层） |
| `detect_overlay(screen)` | `staticmethod → OverlayKind \| None` | 检测当前浮层类型 |
| `has_expedition_ready(screen)` | `staticmethod → bool` | 检测远征完成红点 |
| `has_task_ready(screen)` | `staticmethod → bool` | 检测任务奖励红点 |

#### 导航

| 方法 | 说明 |
|------|------|
| `navigate_to(target: Target)` | 导航到子页面；`Target` 枚举：`SORTIE`/`TASK`/`HOME`/`SIDEBAR`/`EVENT` |
| `dismiss_current_overlay()` | 消除当前浮层，返回 `bool` 表示是否处理 |
| `go_to_sortie()` | 进入地图选择页面的快捷方法 |

---

### 2.2 `MapPage` — 地图页面

> 路径：`autowsgr/ui/map/page.py`（聚合多个 Mixin）

构造：`MapPage(ctrl, ocr=None)`

#### 页面识别与查询（来自 `BaseMapPage`）

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为地图页面 |
| `get_active_panel(screen)` | `staticmethod → MapPanel \| None` | 获取当前激活面板（出征/演习/远征/战役/决战） |
| `has_expedition_notification(screen)` | `staticmethod → bool` | 检测远征完成通知 |
| `find_selected_chapter_y(screen)` | `staticmethod → float \| None` | 扫描侧边栏定位选中章节的 y 坐标 |
| `recognize_map(screen, ocr)` | `staticmethod → MapIdentity \| None` | OCR 识别当前地图（章节+关卡+名称） |

#### 面板导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回主页面 |
| `switch_panel(panel: MapPanel)` | 切换到指定面板标签并验证 |
| `ensure_panel(panel: MapPanel)` | 确保当前在指定面板（不同则切换） |
| `click_screen_center()` | 点击屏幕中央（跳过动画） |

#### 章节导航

| 方法 | 说明 |
|------|------|
| `click_prev_chapter(screen?)` | 点击前一章节 |
| `click_next_chapter(screen?)` | 点击后一章节 |
| `navigate_to_chapter(target: int) → int \| None` | OCR 识别当前位置并逐步导航到目标章节 |

#### 出征面板（`SortiePanelMixin`）

| 方法 | 说明 |
|------|------|
| `enter_sortie(map_num: int)` | 进入指定关卡的出征准备页 |

#### 决战面板（`DecisivePanelMixin`）

| 方法 | 说明 |
|------|------|
| `enter_decisive()` | 进入决战总览页 |

#### 演习面板（`ExercisePanelMixin`）

| 方法 | 说明 |
|------|------|
| `get_opponents(screen)` | 识别对手列表 |
| `select_opponent(index)` | 选择对手 |
| `start_exercise()` | 开始演习 |
| `refresh_opponents()` | 刷新对手列表 |

#### 远征面板（`ExpeditionPanelMixin`）

| 方法 | 说明 |
|------|------|
| `collect_expedition()` | 收取远征奖励 |

---

### 2.3 `BattlePreparationPage` — 出征准备

> 路径：`autowsgr/ui/battle/preparation.py`

构造：`BattlePreparationPage(ctrl, ocr=None)`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为出征准备页面 |
| `get_selected_fleet(screen)` | `staticmethod → int \| None` | 获取选中舰队编号 (1–4) |
| `get_active_panel(screen)` | `staticmethod → Panel \| None` | 获取激活的底部面板 |
| `is_auto_supply_enabled(screen)` | `staticmethod → bool` | 检测自动补给是否开启 |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回地图页面 |

#### 操作

| 方法 | 说明 |
|------|------|
| `start_battle()` | 点击「开始出征」 |
| `select_fleet(fleet: int)` | 选择舰队 (1–4) |
| `select_panel(panel: Panel)` | 切换底部面板（综合战力/快速补给/快速修理/装备预览） |
| `quick_supply()` | 切换到快速补给面板 |
| `quick_repair()` | 切换到快速修理面板 |
| `toggle_battle_support()` | 切换战役支援开关 |
| `toggle_auto_supply()` | 切换自动补给开关 |
| `get_ship_blood_states(screen)` | 获取舰队各位舰船血量状态 (`ShipDamageState` 枚举列表) |

---

### 2.4 `SidebarPage` — 侧边栏

> 路径：`autowsgr/ui/sidebar_page.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为侧边栏（6 个菜单探测点均为灰/蓝） |

#### 导航

| 方法 | 说明 |
|------|------|
| `navigate_to(target: SidebarTarget)` | 进入子页面；`SidebarTarget` 枚举：`BUILD`/`INTENSIFY`/`FRIEND` |
| `go_to_build()` | 进入建造页面 |
| `go_to_intensify()` | 进入强化页面 |
| `go_to_friend()` | 进入好友页面 |
| `close()` | 关闭侧边栏，返回主页面 |

---

### 2.5 `BackyardPage` — 后院

> 路径：`autowsgr/ui/backyard_page.py`

#### 页面识别

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为后院页面（5 个像素签名点） |

#### 导航

| 方法 | 说明 |
|------|------|
| `navigate_to(target: BackyardTarget)` | 进入子页面；`BackyardTarget` 枚举：`BATH`/`CANTEEN` |
| `go_to_bath()` | 进入浴室 |
| `go_to_canteen()` | 进入食堂 |
| `go_back()` | 返回主页面 |

---

### 2.6 `BathPage` — 浴室

> 路径：`autowsgr/ui/bath_page.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为浴室页面（含 overlay 状态） |
| `has_choose_repair_overlay(screen)` | `staticmethod → bool` | 判断「选择修理」overlay 是否打开 |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 关闭 overlay（若已打开）或返回后院 |

#### 操作

| 方法 | 说明 |
|------|------|
| `go_to_choose_repair()` | 打开「选择修理」overlay |
| `close_choose_repair_overlay()` | 关闭「选择修理」overlay |
| `click_first_repair_ship()` | 点击 overlay 中第一个待修舰船 |
| `swipe_repair_list_left()` | 在 overlay 中向左滑动查看更多舰船 |

---

### 2.7 `MissionPage` — 任务

> 路径：`autowsgr/ui/mission_page.py`

#### 页面识别

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 通过标签页检测层识别（`TabbedPageType.MISSION`） |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回主页面 |

#### 操作

| 方法 | 说明 |
|------|------|
| `collect_rewards() → bool` | 收取任务奖励（一键领取 → 单个领取），返回是否成功 |
| `dismiss_reward_popup()` | 关闭领取奖励后的弹窗 |

---

### 2.8 `BuildPage` — 建造

> 路径：`autowsgr/ui/build_page.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 通过标签页检测层识别（`TabbedPageType.BUILD`） |
| `get_active_tab(screen)` | `staticmethod → BuildTab \| None` | 获取当前激活标签（建造/解体/开发/废弃） |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回侧边栏 |
| `switch_tab(tab: BuildTab)` | 切换到指定标签（建造/解体/开发/废弃） |

#### 操作（建造标签）

| 方法 | 说明 |
|------|------|
| `start_build(slot: int)` | 点击指定槽位开始建造 (1–4) |
| `fast_build(slot: int)` | 快速完成指定槽位 |
| `collect_build(slot: int)` | 取出已完成槽位的舰船 |
| `dismiss_build_animation()` | 跳过建造获取动画 |

#### 操作（解体标签）

| 方法 | 说明 |
|------|------|
| `destroy_ships(ship_type?: ShipType)` | 自动解体舰船（可选按舰种过滤） |

---

### 2.9 `IntensifyPage` — 强化

> 路径：`autowsgr/ui/intensify_page.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 通过标签页检测层识别（`TabbedPageType.INTENSIFY`） |
| `get_active_tab(screen)` | `staticmethod → IntensifyTab \| None` | 获取当前激活标签（强化/改修/技能） |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回侧边栏 |
| `switch_tab(tab: IntensifyTab)` | 切换到指定标签并验证 |

---

### 2.10 `FriendPage` — 好友

> 路径：`autowsgr/ui/friend_page.py`

#### 页面识别

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 通过标签页检测层识别（`TabbedPageType.FRIEND`） |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回侧边栏 |

---

### 2.11 `DecisiveBattlePage` — 决战总览

> 路径：`autowsgr/ui/decisive/battle_page.py`

构造：`DecisiveBattlePage(ctrl, ocr=None)`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 判断是否为决战总览页（像素签名） |
| `recognize_stage(screen, chapter)` | 实例方法 `→ list[DecisiveEntryStatus]` | 识别指定章节各小关的通关状态 |
| `recognize_chapter(screen) → int \| None` | 实例方法 | OCR 识别当前章节编号 (4–6) |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回主页面（直接跨级） |
| `navigate_to_chapter(target: int) → bool` | 切换到目标章节（逐步点击前/后翻页） |

#### 操作

| 方法 | 说明 |
|------|------|
| `enter_map()` | 点击中央进入当前章节地图 |
| `click_prev_chapter()` | 切换到前一章节 |
| `click_next_chapter()` | 切换到后一章节 |
| `reset_chapter()` | 点击「重置关卡」 |
| `buy_ticket(resource: str, count: int)` | 购买磁盘资源（oil/ammo/steel/aluminum） |

---

### 2.12 `BaseEventPage` — 活动地图

> 路径：`autowsgr/ui/event/event_page.py`

#### 页面识别与查询

| 方法 | 类型 | 说明 |
|------|------|------|
| `is_current_page(screen)` | `staticmethod → bool` | 识别活动地图页面（含 overlay 弹出状态） |
| `is_hard_mode(screen)` | `staticmethod → bool` | 检测当前是否为困难模式 |
| `is_entrance_alpha(screen)` | `staticmethod → bool` | 检测当前入口是否为 alpha |

#### 导航

| 方法 | 说明 |
|------|------|
| `go_back()` | 返回主页面 |

#### 操作

| 方法 | 说明 |
|------|------|
| `select_node(node_id: int)` | 点击指定节点 |
| `start_fight()` | 点击「出击」按钮，进入出征准备 |
| `switch_difficulty()` | 切换难易模式 |
| `switch_entrance(entrance: Literal["alpha", "beta"])` | 切换入口 |

---

## 三、标签页与枚举速查

### `MapPanel` 枚举

```python
class MapPanel(enum.Enum):
    SORTIE    = "出征"
    EXERCISE  = "演习"
    EXPEDITION = "远征"
    CAMPAIGN  = "战役"
    DECISIVE  = "决战"
```

### `BuildTab` 枚举

```python
class BuildTab(enum.Enum):
    BUILD   = "建造"
    DESTROY = "解体"
    DEVELOP = "开发"
    DISCARD = "废弃"
```

### `IntensifyTab` 枚举

```python
class IntensifyTab(enum.Enum):
    INTENSIFY = "强化"
    REMAKE    = "改修"
    SKILL     = "技能"
```

### `SidebarTarget` 枚举

```python
class SidebarTarget(enum.Enum):
    BUILD     = "建造"
    INTENSIFY = "强化"
    FRIEND    = "好友"
```

### `BackyardTarget` 枚举

```python
class BackyardTarget(enum.Enum):
    BATH    = "浴室"
    CANTEEN = "食堂"
```

---

## 四、常见使用模式

### 跨页面导航（借助导航图）

```python
from autowsgr.ui.navigation import find_path

path = find_path(PageName.MAIN, PageName.BUILD)
if path:
    for edge in path:
        edge.action(ctrl)  # 每条边自行调用对应控制器方法
```

### 等待指定页面

```python
from autowsgr.ui.page import wait_for_page
from autowsgr.ui.build_page import BuildPage

screen = wait_for_page(ctrl, BuildPage.is_current_page, target="建造页")
```

### 创建标签页 checker

```python
from autowsgr.ui.tabbed_page import TabbedPageType, make_tab_checker

# 等待地图页面「远征」标签（索引 2）激活
checker = make_tab_checker(TabbedPageType.MAP, tab_index=2)
screen = wait_for_page(ctrl, checker, target="地图-远征")
```

### 确认弹窗

```python
from autowsgr.ui.page import confirm_operation

found = confirm_operation(ctrl, must_confirm=True, timeout=5.0)
```
