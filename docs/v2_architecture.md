# AutoWSGR V2 (autowsgr) 项目结构文档

> 本文档描述 V2 重构版本（`autowsgr/` 包）的整体架构、分层设计及各文件功能。

---

## 一、总体分层架构

```
用户代码 / 示例脚本
       │
       ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │                         ops/                                    │  ← 游戏操作层
 │  (常规战斗 / 演习 / 远征 / 建造 / 拆解 / 修理 / 导航 …)            │
 └────────────────────────────┬────────────────────────────────────┘
                              │ 调用
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
 ┌──────────┐          ┌──────────┐           ┌──────────┐
 │  combat/ │          │   ui/    │           │  ops/    │
 │ 战斗引擎  │          │ UI页面层 │           │decisive/ │
 └─────┬────┘          └────┬─────┘           └────┬─────┘
       │                   │                       │
       └─────────┬──────────┘                      │
                 ▼                                 │
         ┌──────────────┐                          │
         │  emulator/   │◄─────────────────────────┘
         │ 设备控制层    │
         └──────┬───────┘
                ▼
         ┌──────────────┐
         │   vision/    │
         │   视觉识别层  │
         └──────────────┘
                △
         ┌──────────────┐
         │ image_resources/ │
         │  图像资源注册  │
         └──────────────┘
                △
         ┌──────────────┐
         │    infra/    │
         │ 基础设施层    │
         └──────────────┘
```

---

## 二、顶级文件

### `autowsgr/__init__.py`
包入口，仅声明版本号 `__version__ = "2.0.0-dev"`。

### `autowsgr/types.py`
**全局枚举类型定义**，供全体层次共享引用，包含：

| 枚举/数据类 | 描述 |
|---|---|
| `OSType` | 操作系统类型（Windows / Linux / macOS），支持自动检测 |
| `EmulatorType` | 模拟器类型（雷电 / 蓝叠 / MuMu / 云手机），含注册表查路径逻辑 |
| `OcrBackend` | OCR 后端（easyocr / paddleocr） |
| `GameAPP` | 游戏渠道服（官服 / 小米 / 应用宝），提供包名 |
| `Formation` | 战斗阵型（单纵 / 复纵 / 轮形 / 梯形 / 单横 / 警戒） |
| `FightCondition` | 战况选择（稳步前进 / 火力万岁 等） |
| `ShipDamageState` | 舰船损伤等级（重伤 / 中破 / 小破 / 完好） |
| `ShipType` | 舰种（驱逐 / 轻巡 / 战列 / 航母 等） |
| `RepairMode` | 修理模式（不修 / 中破修 / 小破修） |
| `DestroyShipWorkMode` | 拆船工作模式 |
| `MapEntrance` | 地图入口标识 |
| `PageName` | 页面名称枚举 |
| `ConditionFlag` | 战斗条件标志（SL 触发条件等） |

---

## 三、`infra/` — 基础设施层

提供项目底层能力，不依赖任何游戏逻辑。

### `infra/__init__.py`
统一导出：`ConfigManager`、`UserConfig`、`EmulatorConfig`、`logger`、`AutoWSGRError` 及各子类。

### `infra/config.py`
**配置管理**，基于 Pydantic v2：

- `EmulatorConfig` — 模拟器配置（类型、路径、serial、进程名）
- `AccountConfig` — 账号配置（渠道服）
- `OcrConfig` — OCR 后端选择
- `FightConfig` — 战斗通用配置（修理策略、自动拆船等）
- `NodeConfig` — 单节点战术配置（阵型、夜战、前进条件…）
- `UserConfig` — 融合上述所有子配置的顶层配置对象
- `ConfigManager` — 从 YAML 文件加载并校验配置的工厂类

### `infra/exceptions.py`
**异常层级体系**：

```
AutoWSGRError
├── ConfigError
├── EmulatorError
│   ├── EmulatorConnectionError
│   └── EmulatorNotFoundError
├── VisionError
│   ├── ImageNotFoundError
│   └── OCRError
├── UIError
│   ├── PageNotFoundError
│   ├── NavigationError
│   └── ActionFailedError
├── GameError
│   ├── NetworkError
│   ├── DockFullError
│   └── ResourceError
└── CombatError
    ├── CombatRecognitionTimeout
    └── CombatDecisionError
```

### `infra/logger.py`
**日志系统**。基于 `loguru`，提供 `setup_logger()` 配置日志格式、级别与输出文件路径。

### `infra/file_utils.py`
**文件工具**。提供 `load_yaml()`、`save_yaml()`、路径解析辅助函数等。

---

## 四、`emulator/` — 设备控制层

封装 ADB 设备操作，**不涉及任何图像识别或游戏逻辑**。

### `emulator/__init__.py`
导出 `AndroidController`（实际为 `ADBController`）、`DeviceInfo`。

### `emulator/controller.py`
**核心设备控制器**，基于 `airtest`：

- `DeviceInfo` (dataclass) — 已连接设备的 serial、分辨率信息
- `AndroidController` (抽象基类) — 定义设备操作接口
- `ADBController` (具体实现) — 通过 ADB 控制安卓模拟器：
  - `connect() / disconnect()` — 建立/断开 ADB 连接
  - `screenshot()` — 截图（返回 `np.ndarray`）
  - `click(x, y)` — 点击（使用 0.0–1.0 相对坐标）
  - `swipe(x1, y1, x2, y2)` — 滑动
  - `press_key(key)` — 按键（Home / Back 等）
  - `start_app() / stop_app()` — 启动/停止游戏应用

### `emulator/detector.py`
**模拟器自动检测**：

- `EmulatorCandidate` — 候选模拟器信息（serial、类型、进程名）
- `list_adb_devices()` — 枚举所有已连接 ADB 设备
- `identify_emulator_type()` — 根据 serial 推断模拟器类型
- `detect_emulators()` — 综合检测所有候选模拟器
- `prompt_user_select()` — 交互式多模拟器选择
- `resolve_serial()` — 根据配置自动解析最终 serial

### `emulator/os_control/`
跨平台 OS 层操作（窗口激活、进程管理等）：

| 文件 | 平台 |
|---|---|
| `base.py` | 抽象基类 |
| `windows.py` | Windows（Win32 API） |
| `macos.py` | macOS |
| `linux.py` | Linux / WSL |

---

## 五、`vision/` — 视觉识别层

提供图像匹配和 OCR 能力，不依赖模拟器或游戏逻辑。

### `vision/__init__.py`
导出 `ImageChecker`、`OCREngine`、`EasyOCREngine`、`ImageTemplate`、`ROI` 等。

### `vision/image_template.py`
**图像模板数据模型**：

- `ImageTemplate` — 单张模板图像（路径、ROI、阈值），支持懒加载
- `ImageMatchDetail` — 单次匹配的详细结果（位置、置信度、模板名）
- `ImageMatchResult` — 一组匹配结果（是否命中、最佳匹配等）
- `ImageRule` — 基于模板匹配的页面识别规则（any/all 语义）
- `ImageSignature` — 页面图像签名（多模板组合定义页面特征）

### `vision/pixel.py`
**像素特征数据模型**：

- `Color` — RGB 颜色，支持容差比较（`matches()`）
- `PixelRule` — 单个像素点的颜色规则（坐标 + 期望颜色 + 容差）
- `MatchStrategy` — 匹配策略（ALL / ANY）
- `PixelSignature` — 像素签名（多个 PixelRule 组合，用于页面快速识别）
- `PixelMatchResult` — 像素匹配结果

### `vision/roi.py`
**感兴趣区域（ROI）**：
- `ROI` — 定义裁剪区域（left, top, right, bottom），支持相对坐标，提供 `crop(image)` 方法

### `vision/image_matcher.py`
**图像匹配引擎**：
- 封装 OpenCV 模板匹配（`cv2.matchTemplate`）
- 提供多模板批量匹配、NMS 去重、最优匹配查找

### `vision/matcher.py`
**高层匹配接口 `ImageChecker`**：
- `find_any(screen, templates)` — 在屏幕中查找任意模板
- `find_all(screen, templates)` — 找出所有命中模板
- `match_signature(screen, signature)` — 按签名匹配（用于页面识别）

### `vision/ocr.py`
**OCR 引擎抽象层**：
- `OCREngine` (抽象基类) — 定义 `recognize(image, roi)` 接口
- 支持 EasyOCR / PaddleOCR 两种后端（通过 `OcrBackend` 枚举切换）

### `vision/api_dll.py`
对接外部 DLL（如游戏截图加速 API）的低层调用封装。

---

## 六、`image_resources/` — 图像资源注册层

集中管理所有模板图像的路径与懒加载逻辑，充当**图像资源注册表**。

### `image_resources/_lazy.py`
`LazyTemplate` 实现：声明时记录路径，**首次使用时**才加载图像文件（节省启动时间）。

### `image_resources/__init__.py`
导出 `Templates` 命名空间根对象。

### `image_resources/keys.py`
**模板键类型定义**：提供 `TemplateKey` 枚举或字面量类型，用于类型安全地引用模板。

### `image_resources/combat.py`
战斗相关模板资源：开始出征按钮、撤退按钮、阵型图标、战果等级、血条颜色像素等。

### `image_resources/ops.py`
日常操作相关模板资源：建造、修理、远征、任务奖励、主页元素等。

---

## 七、`ui/` — UI 页面层

将每个游戏页面封装为 Python 类，提供**页面识别**与**页面内操作**两类能力。

### 设计模式
每个页面类通常包含：
- **像素签名** (`PixelSignature`) / **图像签名** (`ImageSignature`) — 用于识别当前是否处于该页面
- **坐标常量** — 该页面内各按钮、元素的点击坐标（相对值）
- **操作方法** — 封装页面内的具体交互逻辑

### `ui/page.py`
`Page` 基类定义，提供通用的签名匹配接口 `is_current(screen)`。

### `ui/navigation.py`
页面导航辅助（页面识别注册表，配合 `ops/navigate.py` 使用）。

### `ui/overlay.py`
通用浮层（弹窗）检测与关闭逻辑（确认框、提示框等）。

### `ui/tabbed_page.py`
多标签页通用基类（如资源选择、舰队编成等）。

### `ui/main_page.py`
主页面（母港主界面）：识别签名 + 各入口按钮坐标。

### `ui/sidebar_page.py`
侧边栏页面（远征、任务等侧栏菜单）。

### `ui/choose_ship_page.py`
选舰页面：舰队编成、舰船列表滚动、选舰逻辑。

### `ui/backyard_page.py`
后院页面：`BackyardTarget` 枚举（浴室、食堂、强化等）、后院入口导航。

### `ui/bath_page.py`
浴室（修理）页面：选修 overlay 的打开/关闭、舰船列表滚动及选舰操作。

### `ui/build_page.py`
建造页面：各资源数量输入坐标、开工/快速建造按钮、建造槽状态检测。

### `ui/canteen_page.py`
食堂页面：食物选择、喂食操作坐标。

### `ui/friend_page.py`
好友页面：好感度相关操作。

### `ui/intensify_page.py`
强化页面：强化操作坐标。

### `ui/mission_page.py`
任务页面：任务列表识别、奖励收取操作。

### `ui/start_screen_page.py`
开始画面页面：游戏启动画面检测与点击跳过。

### `ui/map/`
地图页面组：

| 文件 | 功能 |
|---|---|
| `__init__.py` | 导出 `MapPage` |
| 内部文件 | 章节选择、地图节点坐标、出征路径 |

### `ui/battle/`
战斗准备相关页面：

| 文件 | 功能 |
|---|---|
| `preparation.py` | `BattlePreparationPage` — 出征准备页（舰队选择、补给、出征确认）；`RepairStrategy` — 修理策略枚举 |
| `blood.py` | 血条颜色识别（重伤 / 中破 / 小破 / 完好） |
| `constants.py` | 战斗 UI 坐标常量 |

### `ui/decisive/`
决战模式 UI 组件：

| 文件 | 功能 |
|---|---|
| `preparation.py` | 决战前准备页面 |
| `battle_page.py` | 决战战场 UI |
| `map_controller.py` | 决战地图节点控制 |
| `fleet_ocr.py` | OCR 识别决战舰队信息 |
| `overlay.py` | 决战浮层（命运/奖励等弹窗）处理 |

### `ui/templates/`
页面模板图像（图像签名使用的参考图片）存放目录。

---

## 八、`combat/` — 战斗引擎层

独立于正常 UI 页面框架的**战斗状态机**，驱动从进入地图到战斗结束的全流程。

### `combat/__init__.py`
导出 `CombatEngine`、`CombatPlan`、`CombatResult`、`CombatMode`、`NodeDecision` 等核心类。

### `combat/state.py`
**战斗状态枚举与状态转移图**：

- `CombatPhase` — 所有战斗阶段：
  `START_FIGHT` → `PROCEED` → `FIGHT_CONDITION` → `SPOT_ENEMY_SUCCESS` → `FORMATION` → `MISSILE_ANIMATION` → `FIGHT_PERIOD` → `NIGHT_PROMPT` → `RESULT` → `GET_SHIP` → …
- `PhaseBranch` — 分支动作标签（用于 action-dependent 状态转移）
- `PHASE_TRANSITIONS` / `NORMAL_FIGHT_TRANSITIONS` / `BATTLE_TRANSITIONS` / `EXERCISE_TRANSITIONS` — 不同模式下的合法后继状态字典
- `resolve_successors()` — 根据当前阶段和动作计算下一合法状态集合

### `combat/plan.py`
**YAML 驱动的作战计划**：

- `NodeDecision` (dataclass) — 单节点战术决策（阵型、夜战、前进、SL 条件、索敌规则、迂回等）
- `CombatMode` — 战斗模式枚举（NORMAL / EXERCISE / CAMPAIGN / DECISIVE 等）
- `CombatPlan` — 多节点决策聚合体，支持从 YAML 加载

### `combat/rules.py`
**索敌/阵型规则引擎** `RuleEngine`：
- 根据敌方舰种组成或敌方阵型，动态选择本方阵型或撤退决策
- 支持 YAML 规则配置（`enemy_rules` / `formation_rules`）

### `combat/recognizer.py`
**战斗图像识别器** `CombatRecognizer`：
- 按当前阶段轮询截图，识别当前所处的 `CombatPhase`
- 含超时机制，超时抛出 `CombatRecognitionTimeout`

### `combat/engine.py`
**战斗状态机主循环** `CombatEngine`（继承 `PhaseHandlersMixin`）：
- `run(node_map)` — 驱动从出征到结束的完整状态机循环
- 内部调用识别器确定阶段，调用对应 handler 执行操作
- 顶层函数 `run_combat()` — 对外暴露的最简调用接口

### `combat/handlers.py`
**各阶段操作 mixin** `PhaseHandlersMixin`：

| Handler 方法 | 对应阶段 |
|---|---|
| `_handle_start_fight` | START_FIGHT |
| `_handle_proceed` | PROCEED（前进/回港判断） |
| `_handle_fight_condition` | FIGHT_CONDITION |
| `_handle_spot_enemy_success` | SPOT_ENEMY_SUCCESS（显示敌方编成） |
| `_handle_formation` | FORMATION（选阵型） |
| `_handle_missile_animation` | MISSILE_ANIMATION |
| `_handle_fight_period` | FIGHT_PERIOD（战斗加速） |
| `_handle_night_prompt` | NIGHT_PROMPT（夜战选择） |
| `_handle_result` | RESULT（战果结算） |
| `_handle_get_ship` | GET_SHIP（获取舰船） |
| `_handle_dock_full` | DOCK_FULL（船坞已满） |

### `combat/actions.py`
**战斗操作原子函数**（无状态纯函数）：

| 函数 | 功能 |
|---|---|
| `click_start_march()` | 点击出征按钮 |
| `click_retreat()` | 点击撤退 |
| `click_enter_fight()` | 点击进入战斗 |
| `click_formation(formation)` | 选择阵型 |
| `click_fight_condition(condition)` | 选择战况 |
| `click_night_battle(pursue)` | 夜战选择（追击/撤退） |
| `click_proceed(go_forward)` | 前进/回港 |
| `click_result()` | 点过战果结算 |
| `click_speed_up()` | 战斗加速 |
| `check_blood(device, plan)` | 检测舰队血量是否触发 SL |
| `image_exist()` | 检测图像是否存在 |
| `click_image()` | 等待图像出现后点击 |
| `get_ship_drop()` | OCR 识别掉落舰船名 |
| `get_enemy_info()` | 识别敌方舰种信息 |

### `combat/callbacks.py`
战斗结果数据类 `CombatResult`：记录战果等级、掉落舰船、SL 次数、各节点历史等。

### `combat/history.py`
战斗历史记录：

- `EventType` — 事件类型枚举（进入节点、战斗开始、SL、战果等）
- `CombatEvent` — 单条历史事件
- `FightResult` — 单次战斗结果（节点、阵型、战果等级、掉落）
- `CombatHistory` — 完整出征历史，支持序列化

### `combat/node_tracker.py`
**地图节点跟踪器** `NodeTracker`：
- `MapNodeData` — 节点数据（节点编号、进入次数、战斗次数、SL 次数）
- `NodeTracker` — 维护当前节点状态，根据出征进度更新节点索引

### `combat/recognition.py`
战斗界面专项图像识别辅助，提供：
- 敌方阵型 OCR 识别
- 战果等级（S/A/B/C/D）图像识别
- 舰船血条状态（颜色像素特征）检测

---

## 九、`ops/` — 游戏操作层

将游戏中各类高层操作组织为可复用的函数/类，直接面向用户脚本。

### `ops/__init__.py`
导出 `goto_page`（跨页面导航入口）。

### `ops/navigate.py`
**跨页面导航**：

- `identify_current_page(ctrl)` — 截图并识别当前所处页面名称
- `_goto_page(ctrl, target)` — 单步导航（当前页面 → 目标页面）
- `goto_page(ctrl, target)` — 多步导航（自动规划路径，循环直到到达目标）

### `ops/startup.py`
**游戏启动与初始化**：检测游戏是否运行、启动 App、跳过开场动画、进入主页面。

### `ops/normal_fight.py`
**常规战斗操作** `NormalFightRunner`：

- 路径：主页面 → 地图 → 章节/关卡选择 → 准备 → 战斗 → 循环
- 处理船坞已满自动拆船、自动修理、战斗结果收集
- `run()` — 执行一次完整常规战，返回 `CombatResult`

### `ops/exercise.py`
**演习操作** `ExerciseRunner`：
- 识别演习对手列表、选择目标、进入演习战斗
- `run_exercise()` — 顶层函数

### `ops/expedition.py`
**远征操作**：
- `collect_expedition(ctrl)` — 收取已完成远征奖励
- （后续可扩展派遣远征舰队）

### `ops/build.py`
**舰船建造操作**：

- `BuildRecipe` — 建造配方（各资源数量）
- `collect_built_ships()` — 收取已完成建造舰船
- `build_ship()` — 投入资源开始建造

### `ops/repair.py`
**修理操作**：进入浴室页面，按策略选择舰船进行修理（泡浴 / 快速修理）。

### `ops/destroy.py`
**拆解操作**：进入强化分解界面，按舰种批量拆解舰船。

### `ops/cook.py`
**食堂操作**：进入食堂页面，按配方喂食舰船。

### `ops/campaign.py`
**活动关卡操作**：进入活动地图，执行活动战斗（逻辑与常规战斗类似，但入口不同）。

### `ops/reward.py`
**任务奖励收取**：进入任务页面，批量收取已完成任务奖励。

### `ops/decisive/`
**决战模式操作**（独立子包，逻辑最为复杂）：

| 文件 | 功能 |
|---|---|
| `config.py` | 决战配置（舰队选择、决战章节、节点策略） |
| `state.py` | 决战特有状态枚举（准备阶段 / 战场阶段 / 结算） |
| `base.py` | 决战操作基类，封装通用辅助方法 |
| `chapter.py` | 各决战章节的地图节点数据、机制差异处理 |
| `logic.py` | 决战主逻辑：节点选择、舰队调度、出击决策 |
| `handlers.py` | 决战各阶段 handler（类似 combat/handlers.py） |
| `controller.py` | 决战控制器（入口类），整合 logic / handlers / chapter |

---

## 十、`constants/` — 游戏常量数据

### `constants/shipnames.py`
舰船名称数据（从 `data/shipnames.yaml` 加载），提供舰船名称查找与规范化。

---

## 十一、`data/` — 静态数据资产

| 路径 | 内容 |
|---|---|
| `data/shipnames.yaml` | 所有舰船名称（中文 / 日文 / 缩写等多键） |
| `data/bin/` | 可执行工具（如 ADB 二进制） |
| `data/images/` | 模板图像文件（由 image_resources/ 引用） |
| `data/map/` | 地图节点数据（坐标、连通关系等） |

---

## 十二、关键数据流示例

### 常规战斗调用链

```
examples/battle.py
  └─ NormalFightRunner(ctrl, plan).run()          # ops/normal_fight.py
       ├─ goto_page(ctrl, "map")                  # ops/navigate.py
       ├─ BattlePreparationPage(ctrl).start()     # ui/battle/preparation.py
       └─ run_combat(device, plan)                # combat/engine.py
            ├─ CombatRecognizer.poll()            # combat/recognizer.py
            ├─ PhaseHandlersMixin._handle_*()     # combat/handlers.py
            │   └─ actions.click_*()              # combat/actions.py
            │       └─ AndroidController.click()  # emulator/controller.py
            └─ CombatHistory.record()             # combat/history.py
```

### 页面识别流

```
screen = ctrl.screenshot()                       # emulator/controller.py
page = identify_current_page(ctrl)               # ops/navigate.py
  └─ for page in registered_pages:
       ImageChecker.match_signature(screen, page.signature)   # vision/matcher.py
           └─ PixelSignature.match(screen)       # vision/pixel.py
```

---

## 十三、与 V1 (`autowsgr_legacy/`) 的主要差异

| 方面 | V1 (legacy) | V2 (autowsgr) |
|---|---|---|
| 架构 | 单体 `Timer` 类承担所有职责 | 分层解耦（infra / vision / emulator / ui / combat / ops） |
| 配置 | 松散 dict | Pydantic v2 强类型校验 |
| 坐标系 | 像素绝对坐标 | 0.0–1.0 相对坐标 |
| 战斗驱动 | 轮询 + 条件分支 if/elif | 显式状态机（`CombatPhase` + 转移图） |
| 图像资源 | 散落各处 | 集中于 `image_resources/` 注册 |
| 模拟器检测 | 手动指定 | `emulator/detector.py` 自动检测 |
| 异常体系 | 无统一体系 | 层级化异常（`infra/exceptions.py`） |
| 类型标注 | 稀少 | 全量 type hints + Enum |
