"""Cetus-calibrated intensify controls and fixed-grid occurrence selection.

Semantic identity remains external. This module only resolves already-authorized
opaque references to calibrated target/material grid positions and verifies every
page transition before another input.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from autowsgr.ui.intensify_workflow import (
    ConfirmationCoordinates,
    IntensifyUiState,
    IntensifyWorkflowError,
    SelectionRef,
    VerifiedIntensifyControl,
)
from autowsgr.ui.material_first_intensify import (
    is_intensify_home_screen,
    is_material_selector_screen,
)
from autowsgr.ui.material_inventory_scanner import (
    AdbLosslessMaterialDevice,
    AdbScrollbarStepper,
    has_selected_material,
)


_COLUMN_CENTERS = (0.0948, 0.2047, 0.3146, 0.4250, 0.5349, 0.6448, 0.7547)
_ROW_CENTERS = (0.3343, 0.7352)


class LiveSemanticLedger(Protocol):
    """Recognition library hook for the currently selected semantic transaction."""

    def state(self) -> IntensifyUiState: ...


@dataclass(frozen=True, slots=True)
class GridSelectionRef:
    revision: str
    viewport_steps: int
    row: int
    column: int
    x: float | None = None
    y: float | None = None

    def encode(self, kind: str) -> SelectionRef:
        x = _COLUMN_CENTERS[self.column] if self.x is None else self.x
        y = _ROW_CENTERS[self.row] if self.y is None else self.y
        return SelectionRef(
            f'{kind}:{self.revision}:{self.viewport_steps}:{self.row}:{self.column}:{x:.4f}:{y:.4f}'
        )

    @classmethod
    def parse(cls, ref: SelectionRef, kind: str) -> GridSelectionRef:
        parts = ref.value.split(':')
        if len(parts) != 7 or parts[0] != kind:
            raise IntensifyWorkflowError(f'{kind} 引用格式错误: {ref.value}')
        try:
            result = cls(
                parts[1],
                int(parts[2]),
                int(parts[3]),
                int(parts[4]),
                float(parts[5]),
                float(parts[6]),
            )
        except ValueError as error:
            raise IntensifyWorkflowError(f'{kind} 引用包含无效数字: {ref.value}') from error
        if result.viewport_steps < 0 or result.row not in (0, 1) or not 0 <= result.column < 7:
            raise IntensifyWorkflowError(f'{kind} 引用超出固定网格范围: {ref.value}')
        if (
            result.x is None
            or result.y is None
            or not 0 < result.x < 0.81
            or not 0 < result.y < 0.90
        ):
            raise IntensifyWorkflowError(f'{kind} 引用坐标超出安全卡片区域: {ref.value}')
        return result


class LiveIntensifyStateRecognition:
    """Visual state recognition for the calibrated pages and modal dialog."""

    def __init__(self, device: AdbLosslessMaterialDevice) -> None:
        self._device = device

    def state(self) -> IntensifyUiState:
        screen = self._device.screenshot()
        if is_material_selector_screen(screen):
            return IntensifyUiState.MATERIAL_SELECTOR
        if is_intensify_confirmation(screen):
            return IntensifyUiState.CONFIRMATION
        if is_target_selector(screen):
            return IntensifyUiState.TARGET_SELECTOR
        if is_intensify_home_screen(screen):
            return IntensifyUiState.HOME
        raise IntensifyWorkflowError('无法识别当前强化页面状态')


class FixedTargetOperator:
    """Select a fixed visible target card from a revision-bound first viewport."""

    def __init__(self, device: AdbLosslessMaterialDevice, revision: str) -> None:
        self._device = device
        self._revision = revision

    def select(self, ref: SelectionRef) -> None:
        parsed = GridSelectionRef.parse(ref, 'target')
        if parsed.revision != self._revision or parsed.viewport_steps != 0:
            raise IntensifyWorkflowError('目标引用不是当前已验证首屏 revision')
        if not is_target_selector(self._device.screenshot()):
            raise IntensifyWorkflowError('当前不是目标选择页')
        assert parsed.x is not None
        assert parsed.y is not None
        self._device.click(parsed.x, parsed.y)


class FixedMaterialOperator:
    """Reach one recorded material viewport through scrollbar-only safe movement."""

    def __init__(self, device: AdbLosslessMaterialDevice, revision: str) -> None:
        self._device = device
        self._revision = revision
        self._stepper = AdbScrollbarStepper(device)

    def select(self, ref: SelectionRef) -> None:
        parsed = GridSelectionRef.parse(ref, 'material')
        if parsed.revision != self._revision:
            raise IntensifyWorkflowError('素材引用 revision 已过期')
        screen = self._device.screenshot()
        if not is_material_selector_screen(screen) or has_selected_material(screen):
            raise IntensifyWorkflowError('素材选择前页面不安全或已有选择')
        if not self._stepper.is_top(screen):
            raise IntensifyWorkflowError('素材 occurrence 选择必须从列表顶部开始')
        for _step in range(parsed.viewport_steps):
            screen = self._device.screenshot()
            thumb = self._stepper.thumb_bounds(screen)
            self._stepper.advance(thumb_bottom=thumb[1], screen_height=screen.shape[0])
            time.sleep(0.8)
            moved = self._device.screenshot()
            if not is_material_selector_screen(moved) or has_selected_material(moved):
                raise IntensifyWorkflowError('素材滚动后页面状态不安全')
            if self._stepper.thumb_bounds(moved) == thumb:
                raise IntensifyWorkflowError('素材滚动条没有推进')
        assert parsed.x is not None
        assert parsed.y is not None
        self._device.click(parsed.x, parsed.y)
        time.sleep(0.5)
        if not has_selected_material(self._device.screenshot()):
            raise IntensifyWorkflowError('点击后无法证明素材 occurrence 已选中')


def create_live_intensify_control(
    device: AdbLosslessMaterialDevice,
    recognition: LiveSemanticLedger,
    *,
    target_revision: str,
    material_revision: str,
) -> VerifiedIntensifyControl:
    """Create the calibrated single-material Cetus UI action adapter."""
    device.verify_cetus()
    return VerifiedIntensifyControl(
        device,
        recognition,
        FixedTargetOperator(device, target_revision),
        FixedMaterialOperator(device, material_revision),
        ConfirmationCoordinates(cancel=(0.620, 0.568), confirm=(0.380, 0.568)),
    )


def is_target_selector(screen: object) -> bool:
    """Recognize current target selector from its mutually exclusive right controls."""
    import cv2
    import numpy as np

    image = np.asarray(screen)
    if image.ndim != 3:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    height, width = image.shape[:2]
    switch = hsv[
        round(height * 0.17) : round(height * 0.36),
        round(width * 0.84) : round(width * 0.98),
    ]
    bottom_confirm = hsv[
        round(height * 0.84) : round(height * 0.97),
        round(width * 0.84) : round(width * 0.98),
    ]
    blue_switch = cv2.inRange(switch, np.array((90, 100, 100)), np.array((120, 255, 255)))
    blue_confirm = cv2.inRange(
        bottom_confirm,
        np.array((90, 100, 100)),
        np.array((120, 255, 255)),
    )
    return float(np.mean(blue_switch > 0)) > 0.20 and float(np.mean(blue_confirm > 0)) < 0.20


def is_intensify_confirmation(screen: object) -> bool:
    """Recognize the calibrated four-star intensify confirmation modal."""
    import cv2
    import numpy as np

    image = np.asarray(screen)
    if image.ndim != 3:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    height, width = image.shape[:2]
    header = hsv[
        round(height * 0.24) : round(height * 0.33),
        round(width * 0.29) : round(width * 0.71),
    ]
    confirm = hsv[
        round(height * 0.53) : round(height * 0.61),
        round(width * 0.32) : round(width * 0.44),
    ]
    cancel = hsv[
        round(height * 0.53) : round(height * 0.61),
        round(width * 0.56) : round(width * 0.68),
    ]
    blue_header = cv2.inRange(header, np.array((90, 100, 100)), np.array((120, 255, 255)))
    blue_confirm = cv2.inRange(confirm, np.array((90, 100, 100)), np.array((120, 255, 255)))
    red_cancel = cv2.inRange(cancel, np.array((0, 100, 80)), np.array((10, 255, 255)))
    return (
        float(np.mean(blue_header > 0)) > 0.30
        and float(np.mean(blue_confirm > 0)) > 0.30
        and float(np.mean(red_cancel > 0)) > 0.30
    )
