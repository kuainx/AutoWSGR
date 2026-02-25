"""活动战斗操作 — 活动地图 (Event) 战斗。

涉及跨页面操作: 主页面 → 活动地图页面 → 选择节点 → 出征准备 → 战斗 → 活动地图页面。

参考旧代码: ``fight/event/event_2026_0212.py`` (EventFightPlan20260212)

使用方式::

    from autowsgr.ops.event_fight import EventFightRunner, EventConfig

    config = EventConfig(
        node_positions={
            1: (0.178, 0.209),
            2: (0.384, 0.246),
            3: (0.908, 0.315),
        },
    )
    runner = EventFightRunner(ctx, plan, event_config=config)
    result = runner.run()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from autowsgr.infra.logger import get_logger

from autowsgr.combat import CombatResult, CombatMode, CombatPlan
from autowsgr.combat.engine import run_combat
from autowsgr.ops import goto_page, go_main_page
from autowsgr.types import ConditionFlag, PageName, RepairMode, ShipDamageState
from autowsgr.ui import BattlePreparationPage, RepairStrategy
from autowsgr.ui.event.event_page import BaseEventPage
from autowsgr.emulator import AndroidController
from autowsgr.context import GameContext
from autowsgr.infra import UserConfig
from autowsgr.vision import EasyOCREngine

_log = get_logger("ops")


# ═══════════════════════════════════════════════════════════════════════════════
# 活动配置
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EventConfig:
    """活动特定的配置信息。

    每个活动的地图布局和节点坐标不同，需要单独配置。

    Attributes
    ----------
    node_positions:
        节点入口坐标映射 ``{map_id: (x, y)}``，使用相对坐标 (0.0~1.0)。
        参考旧代码中的 ``NODE_POSITION``。
    difficulty:
        目标难度 ``"H"`` / ``"E"`` / ``None`` (不切换)。
    from_alpha:
        是否从 alpha 入口进入，``None`` 表示不检测。
    popup_coord:
        活动弹窗关闭按钮坐标。部分活动进入时有弹窗需要点击关闭。
    """

    node_positions: dict[int, tuple[float, float]] = field(default_factory=dict)
    difficulty: str | None = None
    from_alpha: bool | None = None
    popup_coord: tuple[float, float] | None = (0.618, 0.564)


# ═══════════════════════════════════════════════════════════════════════════════
# 预设活动配置
# ═══════════════════════════════════════════════════════════════════════════════

# 20260212 活动 — 舰队问答类活动
EVENT_20260212 = EventConfig(
    node_positions={
        1: (0.178125, 0.20925925925925926),
        2: (0.384375, 0.2462962962962963),
        3: (0.9083333333333333, 0.3148148148148148),
        4: (0.27708333333333335, 0.6259259259259259),
        5: (0.5364583333333334, 0.40555555555555556),
        6: (0.6395833333333334, 0.6444444444444445),
    },
)


# ═══════════════════════════════════════════════════════════════════════════════
# 活动战斗执行器
# ═══════════════════════════════════════════════════════════════════════════════


class EventFightRunner:
    """活动战斗执行器。

    与 ``NormalFightRunner`` 结构一致，但导航过程不同：

    - 进入战斗：主页面 → 活动地图 → 选择节点 → 出击 → 出征准备
    - 战斗结束：回到活动地图页面（而非常规地图页面）

    Parameters
    ----------
    ctrl:
        Android 设备控制器。
    plan:
        战斗计划（mode 将被设为 EVENT）。
    event_config:
        活动配置（节点坐标等）。
    config:
        用户全局配置。
    """

    def __init__(
        self,
        ctx: GameContext,
        plan: CombatPlan,
        *,
        event_config: EventConfig | None = None,
    ) -> None:
        self._ctx = ctx
        self._ctrl = ctx.ctrl
        self._plan = plan
        self._event_config = event_config or EventConfig()

        # 从 config 读取拆船配置
        self._dock_full_destroy = ctx.config.dock_full_destroy
        self._destroy_ship_types = ctx.config.destroy_ship_types or None

        # 强制设置为 EVENT 模式
        if plan.mode != CombatMode.EVENT:
            _log.info(
                "[OPS] 活动战斗: 计划模式 {} → EVENT",
                plan.mode,
            )
            plan.mode = CombatMode.EVENT

        self._results: list[CombatResult] = []

    # ── 公共接口 ──

    def run(self) -> CombatResult:
        """执行一次完整的活动战斗。

        Returns
        -------
        CombatResult
        """
        _log.info(
            "[OPS] 活动战: {}-{} ({})",
            self._plan.chapter,
            self._plan.map_id,
            self._plan.name,
        )

        # 1. 进入活动地图并选择节点
        self._enter_fight()

        # 2. 出征准备
        ship_stats = self._prepare_for_battle()

        # 3. 执行战斗
        result = self._do_combat(ship_stats)

        # 4. 处理结果
        self._handle_result(result)

        return result

    def run_for_times(
        self,
        times: int,
        *,
        gap: float = 0.0,
    ) -> list[CombatResult]:
        """重复执行活动战斗。

        Parameters
        ----------
        times:
            重复次数。
        gap:
            每次战斗之间的间隔 (秒)。

        Returns
        -------
        list[CombatResult]
        """
        _log.info("[OPS] 活动战连续执行 {} 次", times)
        self._results = []

        for i in range(times):
            _log.info("[OPS] 活动战第 {}/{} 次", i + 1, times)
            result = self.run()
            self._results.append(result)

            if result.flag == ConditionFlag.DOCK_FULL:
                _log.warning("[OPS] 船坞已满, 停止")
                break

            if gap > 0 and i < times - 1:
                time.sleep(gap)

        _log.info(
            "[OPS] 活动战完成: {} 次 (成功 {} 次)",
            len(self._results),
            sum(1 for r in self._results if r.flag == ConditionFlag.OPERATION_SUCCESS),
        )
        return self._results

    # ── 进入活动地图 ──

    def _enter_fight(self) -> None:
        """导航到活动地图并选择战斗节点。

        流程:
        1. 回到主页面
        2. 点击活动入口进入活动地图
        3. 处理可能的弹窗
        4. 切换难度（如配置）
        5. 选择地图节点
        6. 点击出击进入出征准备
        """
        # 回到主页面再进入活动
        go_main_page(self._ctrl)
        time.sleep(0.5)

        # 进入活动地图
        goto_page(self._ctrl, PageName.EVENT_MAP)
        time.sleep(1.0)

        # 处理活动弹窗 (部分活动进入时有弹窗)
        self._handle_popup()

        # 切换难度
        event_page = BaseEventPage(
            self._ctx,
        )

        if self._event_config.difficulty is not None:
            event_page._change_difficulty(self._event_config.difficulty)
            # chapter 为 H/E 时使用 chapter 作为难度
        elif isinstance(self._plan.chapter, str) and self._plan.chapter.upper() in ("H", "E"):
            event_page._change_difficulty(self._plan.chapter)

        # 选择节点
        map_id = self._plan.map_id
        if isinstance(map_id, str):
            map_id = int(map_id)
        event_page.select_node(map_id)
        time.sleep(0.5)

        # 点击出击
        event_page.start_fight()

    def _handle_popup(self) -> None:
        """处理活动弹窗。

        部分活动进入活动地图时会弹出公告/活动说明等弹窗，
        需要点击关闭按钮才能操作。
        """
        coord = self._event_config.popup_coord
        if coord is None:
            return

        # 等待一小段时间看是否有弹窗
        time.sleep(0.8)
        screen = self._ctrl.screenshot()

        # 检测是否仍在活动地图（无弹窗时页面应正常匹配）
        if BaseEventPage.is_current_page(screen):
            return  # 无弹窗

        # 有弹窗，点击关闭
        _log.info("[OPS] 活动战: 检测到弹窗, 点击关闭")
        self._ctrl.click(*coord)
        time.sleep(1.0)

    # ── 出征准备 ──

    def _prepare_for_battle(self) -> list[ShipDamageState]:
        """出征准备: 舰队选择、修理、检测血量。"""
        time.sleep(1.0)
        page = BattlePreparationPage(self._ctx)

        # 选择舰队
        page.select_fleet(self._plan.fleet_id)
        time.sleep(0.5)

        # 换船 (如果指定了舰船列表)
        if self._plan.fleet is not None:
            page.change_fleet(
                self._plan.fleet_id,
                self._plan.fleet,
            )
            time.sleep(0.5)

        # 补给
        page.apply_supply()
        time.sleep(0.3)

        # 修理策略
        repair_modes = self._plan.repair_mode
        if isinstance(repair_modes, list):
            min_mode = min(m.value for m in repair_modes)
        else:
            min_mode = repair_modes.value

        if min_mode <= RepairMode.moderate_damage.value:
            page.apply_repair(RepairStrategy.MODERATE)
        elif min_mode <= RepairMode.severe_damage.value:
            page.apply_repair(RepairStrategy.SEVERE)

        # 检测战前血量
        screen = self._ctrl.screenshot()
        damage = page.detect_ship_damage(screen)
        ship_stats = [
            damage.get(i, ShipDamageState.NORMAL) for i in range(6)
        ]

        # 出征
        page.start_battle()
        time.sleep(1.0)

        return ship_stats

    # ── 战斗 ──

    def _do_combat(self, ship_stats: list[ShipDamageState]) -> CombatResult:
        """构建 CombatEngine 并执行战斗。"""
        return run_combat(
            self._ctx,
            self._plan,
            ship_stats=ship_stats,
        )

    # ── 结果处理 ──

    def _handle_result(self, result: CombatResult) -> None:
        """处理战斗结果。"""
        if result.flag == ConditionFlag.DOCK_FULL:
            self._handle_dock_full(result)
            return
        _log.info("[OPS] 活动战结果: {}", result.flag.value)

    def _handle_dock_full(self, result: CombatResult) -> None:
        """船坞已满处理。"""
        if self._dock_full_destroy:
            from autowsgr.ops.destroy import destroy_ships

            _log.warning("[OPS] 船坞已满，执行自动解装")
            self._ctrl.click(0.38, 0.565)
            destroy_ships(
                self._ctrl,
                ship_types=self._destroy_ship_types,
            )
            result.flag = ConditionFlag.OPERATION_SUCCESS
            return

        _log.warning("[OPS] 船坞已满, 未开启自动解装")


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════


def run_event_fight(
    ctx: GameContext,
    plan: CombatPlan,
    *,
    event_config: EventConfig | None = None,
    times: int = 1,
    gap: float = 0.0,
) -> list[CombatResult]:
    """执行活动战的便捷函数。

    Parameters
    ----------
    ctx:
        游戏上下文。
    plan:
        战斗计划。
    event_config:
        活动配置。
    times:
        重复次数。
    gap:
        每次间隔。

    Returns
    -------
    list[CombatResult]
    """
    runner = EventFightRunner(
        ctx,
        plan,
        event_config=event_config,
    )
    return runner.run_for_times(times, gap=gap)


def run_event_fight_from_yaml(
    ctx: GameContext,
    yaml_path: str,
    *,
    event_config: EventConfig | None = None,
    times: int = 1,
    **kwargs,
) -> list[CombatResult]:
    """从 YAML 文件加载计划并执行活动战。

    Parameters
    ----------
    ctx:
        游戏上下文。
    yaml_path:
        YAML 配置路径。
    event_config:
        活动配置。
    times:
        重复次数。
    **kwargs:
        传递给 ``run_event_fight`` 的额外参数。

    Returns
    -------
    list[CombatResult]
    """
    plan = CombatPlan.from_yaml(yaml_path)
    return run_event_fight(
        ctx, plan,
        event_config=event_config,
        times=times,
        **kwargs,
    )
