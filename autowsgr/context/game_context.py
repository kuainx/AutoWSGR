"""顶层游戏状态聚合。"""

from __future__ import annotations

from dataclasses import dataclass, field

from autowsgr.types import PageName

from .build import BuildQueue
from .expedition import ExpeditionQueue
from .fleet import Fleet
from .resources import Resources

# 游戏固定 4 支舰队
_NUM_FLEETS = 4


def _default_fleets() -> list[Fleet]:
    return [Fleet(fleet_id=i) for i in range(1, _NUM_FLEETS + 1)]


@dataclass
class GameContext:
    """运行时可观测的游戏状态聚合。

    **不含**配置 (UserConfig) 或基础设施 (Logger)；
    仅描述从游戏画面中读取 / 推断出的动态数据。
    各子模块在执行操作时负责写入对应字段。
    """

    resources: Resources = field(default_factory=Resources)
    """当前资源。"""
    fleets: list[Fleet] = field(default_factory=_default_fleets)
    """四支舰队 (fleet_id 1–4)。"""
    expeditions: ExpeditionQueue = field(default_factory=ExpeditionQueue)
    """远征队列。"""
    build_queue: BuildQueue = field(default_factory=BuildQueue)
    """建造队列。"""
    current_page: PageName | None = None
    """当前游戏页面。"""

    # ── 每日计数器 ──

    dropped_ship_count: int = 0
    """当天掉落舰船数。"""
    dropped_loot_count: int = 0
    """当天掉落胖次数。"""
    quick_repair_used: int = 0
    """本次会话已消耗快修数。"""

    # ── 便捷访问 ──

    def fleet(self, fleet_id: int) -> Fleet:
        """按编号 (1–4) 获取舰队。"""
        if not 1 <= fleet_id <= len(self.fleets):
            raise ValueError(
                f"fleet_id 应在 1–{len(self.fleets)} 范围内，收到 {fleet_id}"
            )
        return self.fleets[fleet_id - 1]
