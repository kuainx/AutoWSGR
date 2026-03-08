"""舰队编成更换 -- 更换算法。

实现 "扫描 -> 定点更换 -> 调整次序" 的统一换船流程,
对齐 legacy ``Fleet._set_ships`` / ``Fleet.reorder`` 算法。

常规出征与决战共用此 Mixin, 通过实例属性 ``_use_search``
控制选船页面是否使用搜索框:

- ``True`` (默认): 常规出征, 使用搜索框输入舰船名
- ``False``: 决战模式, 直接 OCR 列表点击
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from autowsgr.infra.logger import get_logger
from autowsgr.ui.battle.constants import CLICK_SHIP_SLOT

from ._detect import FleetDetectMixin


if TYPE_CHECKING:
    from collections.abc import Sequence


_log = get_logger('ui.preparation')

# change_fleet 最大重试次数 (对齐 legacy Fleet.set_ship 的 max_retries=2)
_MAX_SET_RETRIES: int = 2

# 等待选船页面出现的超时 (秒)
_CHOOSE_PAGE_TIMEOUT: float = 5.0


class FleetChangeMixin(FleetDetectMixin):
    """舰队编成更换 Mixin。

    实例属性 ``_use_search`` 控制选船页面是否使用搜索框:

    - ``True`` (默认): 常规出征, 使用搜索框输入舰船名
    - ``False``: 决战模式, 直接 OCR 列表点击

    依赖 :class:`~autowsgr.ui.battle.base.BaseBattlePreparation` 提供的
    ``_ctx``, ``_ctrl``, ``_ocr``, ``click_ship_slot``,
    ``get_selected_fleet``, ``select_fleet``,
    以及 :class:`._detect.FleetDetectMixin` 提供的
    ``detect_fleet``, ``_validate_fleet``。
    """

    _use_search: bool = True

    # ══════════════════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════════════════

    def change_fleet(
        self,
        fleet_id: int | None,
        ship_names: Sequence[str | None],
    ) -> bool:
        """更换编队全部舰船 -- 扫描 -> 定点更换 -> 调整次序。

        **三步算法** (对齐 legacy ``Fleet._set_ships`` + ``Fleet.reorder``):

        1. **扫描**: OCR 识别当前舰队, 前置短路判断是否已满足目标。
        2. **成员对齐** (``_set_ships``): 标记 ok/not-ok, 定点替换缺失舰船,
           从后往前移除多余舰船。
        3. **位置对齐** (``_reorder``): 通过滑动拖拽将每艘船移到正确槽位。

        失败时自动重试 (最多 ``_MAX_SET_RETRIES`` 次)。

        Parameters
        ----------
        fleet_id:
            舰队编号 (2-4); ``None`` 代表不指定舰队。1 队不支持更换。
        ship_names:
            目标舰船名列表 (按槽位 0-5 顺序); ``None``/``""`` 表示留空。

        Returns
        -------
        bool
            ``True`` 表示最终验证通过, ``False`` 表示全部重试失败。
        """
        if fleet_id == 1:
            raise ValueError('不支持更换 1 队舰船编成')

        if fleet_id and self.get_selected_fleet(self._ctrl.screenshot()) != fleet_id:
            self.select_fleet(fleet_id)
            time.sleep(0.5)

        names: list[str | None] = [(n or None) for n in list(ship_names)[:6]]
        names += [None] * (6 - len(names))
        _log.info('[准备页] 目标编成: {}', names)

        for attempt in range(_MAX_SET_RETRIES + 1):
            # ── 1. 扫描当前舰队 ──────────────────────────────────────
            current = self.detect_fleet()

            # ── 前置短路: 已满足则无需任何操作 ────────────────────────
            if self._validate_fleet(current, names):
                _log.info('[准备页] 舰队已满足目标, 跳过换船')
                return True

            desired_set: set[str] = {n for n in names if n is not None}

            # ── 2. 成员对齐: 确保目标船都在队中 ──────────────────────
            ok: list[bool] = [False] * 6
            for i in range(6):
                if current[i] is not None and current[i] in desired_set:
                    ok[i] = True

            for name in names:
                if name is None:
                    continue
                if name in current:
                    continue
                slot = next((i for i in range(6) if not ok[i]), None)
                if slot is None:
                    _log.warning("[准备页] 无可用槽位放 '{}', 跳过", name)
                    continue
                occupied = current[slot] is not None
                _log.info(
                    "[准备页] 成员对齐: 槽位 {} <- '{}' (原: '{}')",
                    slot,
                    name,
                    current[slot],
                )
                self._change_single_ship(slot, name, slot_occupied=occupied)
                current[slot] = name
                ok[slot] = True
                time.sleep(0.3)

            # 从后往前移除剩余不需要的舰船
            for i in range(5, -1, -1):
                if not ok[i] and current[i] is not None:
                    _log.info("[准备页] 移除槽位 {} 的 '{}'", i, current[i])
                    self._change_single_ship(i, None, slot_occupied=True)
                    current[i] = None
                    time.sleep(0.3)

            # ── 3. 位置对齐: 滑动拖拽到正确槽位 ─────────────────────
            current = self.detect_fleet()
            self._reorder(current, names)

            # ── 4. 验证结果 ──────────────────────────────────────────
            current = self.detect_fleet()
            if self._validate_fleet(current, names):
                _log.info('[准备页] 编成更换完成: {}', current)
                return True

            if attempt < _MAX_SET_RETRIES:
                _log.warning(
                    '[准备页] 第 {}/{} 次验证失败, 重试...',
                    attempt + 1,
                    _MAX_SET_RETRIES + 1,
                )
                time.sleep(0.5)
            else:
                _log.error(
                    '[准备页] 舰队设置在 {} 次尝试后仍然失败, 当前: {}',
                    _MAX_SET_RETRIES + 1,
                    current,
                )

        return False

    # ══════════════════════════════════════════════════════════════════════
    # 位置对齐
    # ══════════════════════════════════════════════════════════════════════

    def _reorder(
        self,
        current: list[str | None],
        desired: list[str | None],
    ) -> None:
        """通过滑动将舰船移至目标位置 (对齐 legacy ``Fleet.reorder``)。

        从左到右逐槽位检查, 若当前位置不是目标船则找到目标船所在
        槽位, 通过 ``_circular_move`` 滑动到正确位置。

        Parameters
        ----------
        current:
            **变参**: 当前 6 槽位舰船名, 本方法会就地修改。
        desired:
            目标 6 槽位舰船名。
        """
        for i in range(6):
            target = desired[i]
            if target is None:
                break  # 对齐 legacy: 遇到空位即停止
            if current[i] == target:
                continue
            try:
                src = current.index(target)
            except ValueError:
                _log.warning(
                    "[准备页] 位置对齐: '{}' 不在当前舰队中, 跳过",
                    target,
                )
                continue
            _log.info(
                "[准备页] 位置对齐: 槽位 {} <- '{}' (从槽位 {})",
                i,
                target,
                src,
            )
            self._circular_move(src, i, current)

    def _circular_move(
        self,
        src: int,
        dst: int,
        current: list[str | None],
    ) -> None:
        """滑动将舰船从 *src* 槽位移至 *dst* 槽位。

        游戏行为: 拖拽 src 到 dst 后, src 与 dst 之间的舰船做循环位移。

        Parameters
        ----------
        src:
            源槽位 (0-5)。
        dst:
            目标槽位 (0-5)。
        current:
            **变参**: 当前 6 槽位舰船名, 就地更新以反映移动后状态。
        """
        if src == dst:
            return
        sx, sy = CLICK_SHIP_SLOT[src]
        dx, dy = CLICK_SHIP_SLOT[dst]
        self._ctrl.swipe(sx, sy, dx, dy, duration=0.5)

        # 更新本地追踪 (circular shift, 对齐 legacy)
        ship = current.pop(src)
        current.insert(dst, ship)
        time.sleep(0.5)

    # ══════════════════════════════════════════════════════════════════════
    # 单船更换
    # ══════════════════════════════════════════════════════════════════════

    def _change_single_ship(
        self,
        slot: int,
        name: str | None,
        *,
        slot_occupied: bool = True,
    ) -> None:
        """更换/移除指定位置的单艘舰船。

        点击槽位 -> 进入选船页面 -> 委托给
        :meth:`~autowsgr.ui.choose_ship_page.ChooseShipPage.change_single_ship`
        完成实际操作 (根据 ``_use_search`` 决定是否使用搜索框)。
        """
        from autowsgr.ui.choose_ship_page import ChooseShipPage
        from autowsgr.ui.utils import wait_for_page

        if name is None and not slot_occupied:
            return

        self.click_ship_slot(slot)
        wait_for_page(
            self._ctrl,
            ChooseShipPage.is_current_page,
            timeout=_CHOOSE_PAGE_TIMEOUT,
        )
        choose_page = ChooseShipPage(self._ctx)
        choose_page.change_single_ship(name, use_search=self._use_search)
