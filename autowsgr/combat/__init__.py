"""战斗系统 — 独立于 UI 框架的战斗状态机引擎。
"""

from .plan import CombatMode, CombatPlan, NodeDecision
from .state import CombatPhase
from .rules import RuleEngine, RuleResult
from .history import CombatHistory, CombatEvent, CombatResult
from .node_tracker import MapNodeData, NodeTracker
from .engine import CombatEngine, run_combat
from .recognition import recognize_enemy_formation

__all__ = [
    "CombatPhase",
    "CombatResult",
    "RuleEngine",
    "RuleResult",
    "CombatPlan",
    "NodeDecision",
    "CombatHistory",
    "CombatEvent",
    "MapNodeData",
    "NodeTracker",
    "CombatEngine",
    "CombatMode",
    "run_combat",
    "recognize_enemy_formation",
]
