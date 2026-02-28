"""最小示例 — 常规作战 (7-4 千伪)。

使用内置策略 ``7-4千伪`` 执行 3 次常规作战。
策略文件自动从 ``autowsgr/data/plan/normal_fight/`` 解析，无需指定完整路径。
"""

from autowsgr.scheduler import launch
from autowsgr.ops import goto_page
from autowsgr.ui import BattlePreparationPage, PageName

# 1. 启动 (加载配置 → 连接模拟器 → 启动游戏)
ctx = launch('usersettings.yaml')

goto_page(ctx, PageName.BATTLE_PREP)

page = BattlePreparationPage(ctx)

page.change_fleet(2, ["U-47", "U-96"])
