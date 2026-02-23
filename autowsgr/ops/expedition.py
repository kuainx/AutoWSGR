"""远征操作。

检查主页面远征通知, 导航到地图页面委托 UI 层收取。
"""

from __future__ import annotations

from autowsgr.infra.logger import get_logger

from autowsgr.emulator import AndroidController
from autowsgr.ops.navigate import goto_page
from autowsgr.types import PageName
from autowsgr.ui.main_page import MainPage
from autowsgr.ui.map.page import MapPage
from autowsgr.ui.map.data import MapPanel

_log = get_logger("ops")


def collect_expedition(ctrl: AndroidController) -> bool:
    """收取已完成的远征。
    
    已完成，测试通过

    Returns
    -------
    bool
        是否执行了收取操作。
    """
    _log.info("[OPS] 开始检查远征收取")
    goto_page(ctrl, PageName.MAIN)
    screen = ctrl.screenshot()
    if not MainPage.has_expedition_ready(screen):
        _log.debug("[OPS] 无远征可收取")
        return False

    goto_page(ctrl, PageName.MAP)
    page = MapPage(ctrl)

    screen = ctrl.screenshot()
    if not MapPage.has_expedition_notification(screen):
        goto_page(ctrl, PageName.MAIN)
        return False

    page.switch_panel(MapPanel.EXPEDITION)

    collected = page.collect_expedition()

    goto_page(ctrl, PageName.MAIN)
    _log.info("[OPS] 远征收取完成")
    return collected > 0
