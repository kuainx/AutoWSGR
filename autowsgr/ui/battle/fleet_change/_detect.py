"""舰队编成更换 -- 准备页舰队检测。

提供 OCR 检测出征准备页面当前 6 个槽位舰船名的能力,
以及目标校验工具函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autowsgr.constants import SHIPNAMES
from autowsgr.infra.logger import get_logger
from autowsgr.ui.battle.base import BaseBattlePreparation
from autowsgr.vision.ocr import _fuzzy_match


if TYPE_CHECKING:
    import numpy as np


_log = get_logger('ui.preparation')

# 出征准备页下方舰船名称标签横条的 Y 范围 (相对坐标)
# 实测 1280x720 截图: 舰船名字中心 y ~ 447, 故取 y in [435, 462]
_NAME_STRIP_Y1: float = 435 / 720
_NAME_STRIP_Y2: float = 462 / 720

# 6 个舰船槽位对应的 X 中心相对坐标 (与 CLICK_SHIP_SLOT 一致)
_SLOT_X_CENTERS: tuple[float, ...] = (
    0.1146,
    0.2292,
    0.3438,
    0.4583,
    0.5729,
    0.6875,
)

# 舰船名模糊匹配编辑距离阈值
_SHIP_FUZZY_THRESHOLD: int = 2


class FleetDetectMixin(BaseBattlePreparation):
    """准备页舰队 OCR 检测 Mixin。

    依赖 :class:`~autowsgr.ui.battle.base.BaseBattlePreparation` 提供的
    ``_ctrl``, ``_ocr``。
    """

    def detect_fleet(self, screen: np.ndarray | None = None) -> list[str | None]:
        """OCR 识别出征准备页面当前 6 个槽位的舰船名。

        读取屏幕底部舰船名称横条中的各块文字,
        按 X 坐标对应到槽位 0-5。

        Parameters
        ----------
        screen:
            截图 (HxWx3, RGB); ``None`` 时自动截图。

        Returns
        -------
        list[str | None]
            长度为 6 的列表, 槽位未占用时为 ``None``。
        """
        if screen is None:
            screen = self._ctrl.screenshot()

        h, w = screen.shape[:2]
        y1 = int(_NAME_STRIP_Y1 * h)
        y2 = int(_NAME_STRIP_Y2 * h)
        strip = screen[y1:y2, :]

        results = self._ocr.recognize(strip)
        ships: list[str | None] = [None] * 6

        for r in results:
            text = r.text.strip()
            if not text or r.bbox is None:
                continue
            matched = _fuzzy_match(text, SHIPNAMES, _SHIP_FUZZY_THRESHOLD)
            if matched is None:
                continue
            cx_rel = (r.bbox[0] + r.bbox[2]) / 2 / w
            slot = min(
                range(6),
                key=lambda i, cx=cx_rel: abs(_SLOT_X_CENTERS[i] - cx),
            )
            ships[slot] = matched
            _log.debug("[准备页] 槽位 {} OCR -> '{}'", slot, matched)

        _log.info('[准备页] 当前舰队: {}', ships)
        return ships

    @staticmethod
    def _validate_fleet(
        current: list[str | None],
        desired: list[str | None],
    ) -> bool:
        """验证当前舰队是否已满足目标 (逐槽位精确比对)。

        Parameters
        ----------
        current:
            OCR 识别到的当前 6 槽位舰船名 (``None`` 为空)。
        desired:
            目标 6 槽位舰船名列表 (``None`` 为空)。

        Returns
        -------
        bool
            ``True`` 表示每个槽位的舰船都与目标一致。
        """
        for i in range(6):
            c = current[i]
            d = desired[i]
            if d is None:
                continue
            if c != d:
                return False
        return True
