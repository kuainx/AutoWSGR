"""Cetus adapters for read-only target inventory scanning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import cv2
import numpy as np

from autowsgr.ui.intensify_workflow import ShipStats
from autowsgr.ui.live_intensify import is_target_selector
from autowsgr.ui.target_inventory_scanner import (
    CardRect,
    TargetCardIdentity,
    TargetInventoryScanError,
    TargetInventoryScanner,
    TargetShipSnapshot,
)


if TYPE_CHECKING:
    from autowsgr.ui.material_inventory_scanner import AdbLosslessMaterialDevice
    from autowsgr.vision.ocr import OCREngine
    from autowsgr.vision.ship_portrait_matcher import ShipPortraitLibrary


_PORTRAIT_CROP = (0.03, 0.02, 0.97, 0.59)
_STRENGTHEN_CROPS = (
    (0.14, 0.60, 0.24, 0.80),
    (0.38, 0.60, 0.48, 0.80),
    (0.62, 0.60, 0.72, 0.80),
    (0.86, 0.60, 0.96, 0.80),
)
_TRACK_X_1920 = 1580
_TRACK_TOP_1080 = 130
_TRACK_BOTTOM_1080 = 1034
_PAUSE_FILE = Path(r'C:\Users\23264\AppData\Local\Temp\kilo\pause-expedition-daemon')


class TargetStatFallback(Protocol):
    def __call__(self, image: np.ndarray) -> int | None: ...


def _relative_crop(
    screen: np.ndarray,
    card: CardRect,
    bounds: tuple[float, float, float, float],
) -> np.ndarray:
    x1, y1, x2, y2 = bounds
    width = card.right - card.left
    height = card.bottom - card.top
    return screen[
        card.top + round(height * y1) : card.top + round(height * y2),
        card.left + round(width * x1) : card.left + round(width * x2),
    ]


def _average_hash(image: np.ndarray, size: int = 16) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    bits = resized >= float(resized.mean())
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return value


def target_thumb_bounds(screen: np.ndarray) -> tuple[int, int]:
    """Locate the shorter target-list thumb on the shared right-side track."""
    height, width = screen.shape[:2]
    x = min(width - 1, round(_TRACK_X_1920 * width / 1920))
    column = screen[:, x].astype(np.int16)
    neutral = np.max(column, axis=1) - np.min(column, axis=1) <= 12
    light = np.min(column, axis=1) >= 150
    track_top = round(_TRACK_TOP_1080 * height / 1080)
    track_bottom = round(_TRACK_BOTTOM_1080 * height / 1080)
    mask = neutral & light
    mask[:track_top] = False
    mask[track_bottom:] = False
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for y, present in enumerate(mask):
        if present and start is None:
            start = y
        elif not present and start is not None:
            if y - start >= round(60 * height / 1080):
                runs.append((start, y))
            start = None
    if start is not None and track_bottom - start >= round(60 * height / 1080):
        runs.append((start, track_bottom))
    if len(runs) != 1:
        raise TargetInventoryScanError(f'目标滚动条滑块定位不唯一: {runs}')
    return runs[0]


def _is_cross(crop: np.ndarray) -> bool:
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array((90, 120, 60)), np.array((130, 255, 255)))
    height, width = mask.shape
    center = mask[
        round(height * 0.10) : round(height * 0.85),
        round(width * 0.15) : round(width * 0.95),
    ]
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(center)
    diagonals = [
        index
        for index in range(1, count)
        if 7 <= stats[index, cv2.CC_STAT_HEIGHT] <= round(height * 0.45)
        and 4 <= stats[index, cv2.CC_STAT_WIDTH] <= round(width * 0.35)
        and 20 <= stats[index, cv2.CC_STAT_AREA] <= 90
    ]
    return len(diagonals) >= 2


def _topology_digit(crop: np.ndarray) -> int | None:
    """Recognize reliable zero/one topology; leave other digits to a fallback."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array((90, 150, 70)), np.array((125, 255, 255)))
    mask[: round(mask.shape[0] * 0.18), :] = 0
    mask[round(mask.shape[0] * 0.88) :, :] = 0
    mask[:, : round(mask.shape[1] * 0.12)] = 0
    mask[:, round(mask.shape[1] * 0.94) :] = 0
    count, labels, stats, _centers = cv2.connectedComponentsWithStats(mask)
    accepted = [
        label
        for label in range(1, count)
        if 7 <= stats[label, cv2.CC_STAT_HEIGHT] <= round(mask.shape[0] * 0.55)
        and 2 <= stats[label, cv2.CC_STAT_WIDTH] <= round(mask.shape[1] * 0.50)
        and stats[label, cv2.CC_STAT_AREA] >= 8
    ]
    if not accepted:
        return None
    cleaned = np.zeros_like(mask)
    for label in accepted:
        cleaned[labels == label] = 255
    points = cv2.findNonZero(cleaned)
    if points is None:
        return None
    x, y, width, height = cv2.boundingRect(points)
    glyph = cleaned[y : y + height, x : x + width]
    _contours, hierarchy = cv2.findContours(glyph, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else sum(1 for item in hierarchy[0] if item[3] >= 0)
    if holes == 1:
        return 0
    column_ink = (glyph > 0).sum(axis=0)
    if height >= 14 and int((column_ink >= height - 2).sum()) >= 3:
        return 1
    return None


def _is_max(crop: np.ndarray) -> bool:
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    orange = cv2.inRange(hsv, np.array((5, 150, 140)), np.array((35, 255, 255)))
    orange[:, : round(orange.shape[1] * 0.12)] = 0
    orange[:, round(orange.shape[1] * 0.92) :] = 0
    orange[: round(orange.shape[0] * 0.12), :] = 0
    orange[round(orange.shape[0] * 0.90) :, :] = 0
    return int((orange > 0).sum()) >= max(12, crop.shape[0] * crop.shape[1] // 20)


@dataclass(slots=True)
class CetusTargetCardReader:
    portraits: ShipPortraitLibrary
    ocr: OCREngine | None = None

    def identify(self, screen: np.ndarray, card: CardRect) -> TargetCardIdentity | None:
        portrait = _relative_crop(screen, card, _PORTRAIT_CROP)
        match = self.portraits.identify(portrait)
        if match is None:
            return None
        return TargetCardIdentity(
            ship_id=match.record.ship_id,
            name=match.record.name,
            ship_type=match.record.ship_type,
            visual_hash=_average_hash(portrait),
            portrait_good_matches=match.good_matches,
            portrait_match_ratio=match.ratio,
        )

    def _read_stat(self, crop: np.ndarray) -> int | None:
        if _is_cross(crop):
            return 0
        if _is_max(crop):
            return None
        topology = _topology_digit(crop)
        if topology is not None:
            return topology
        if self.ocr is None:
            return None
        value = self.ocr.recognize_number(crop)
        return value if value is not None and 0 <= value <= 999 else None

    def read_levels(self, screen: np.ndarray, card: CardRect) -> ShipStats | None:
        values = [self._read_stat(_relative_crop(screen, card, bounds)) for bounds in _STRENGTHEN_CROPS]
        if any(value is None for value in values):
            return None
        firepower, torpedo, armor, anti_air = values
        assert firepower is not None
        assert torpedo is not None
        assert armor is not None
        assert anti_air is not None
        return ShipStats(firepower, torpedo, armor, anti_air)


class CetusTargetScanDevice:
    def __init__(self, device: AdbLosslessMaterialDevice, *, step_pixels: int = 11) -> None:
        self._device = device
        self._step_pixels = step_pixels

    def screenshot(self) -> np.ndarray:
        screen = self._device.screenshot()
        if not is_target_selector(screen):
            raise TargetInventoryScanError('当前不是安全目标选择页')
        target_thumb_bounds(screen)
        return screen

    def _swipe_track(self, start_y: int, end_y: int, screen_height: int) -> None:
        width, device_height = self._device.resolution
        x = round(_TRACK_X_1920 * width / 1920)
        scale = device_height / screen_height
        self._device.shell(
            f'input swipe {x} {round(start_y * scale)} {x} {round(end_y * scale)} 300'
        )

    def rewind_target_list(self) -> None:
        for _attempt in range(10):
            screen = self.screenshot()
            top, bottom = target_thumb_bounds(screen)
            target_top = round(_TRACK_TOP_1080 * screen.shape[0] / 1080)
            if top <= target_top + round(10 * screen.shape[0] / 1080):
                return
            self._swipe_track((top + bottom) // 2, target_top, screen.shape[0])
        raise TargetInventoryScanError('目标列表回顶超过最大尝试次数')

    def advance_target_list(self) -> None:
        screen = self.screenshot()
        top, bottom = target_thumb_bounds(screen)
        start = max(top + 1, bottom - round(20 * screen.shape[0] / 1080))
        end = min(
            round(_TRACK_BOTTOM_1080 * screen.shape[0] / 1080) - 1,
            start + max(1, round(self._step_pixels * screen.shape[0] / 1080)),
        )
        self._swipe_track(start, end, screen.shape[0])


def scan_live_target_inventory(
    device: AdbLosslessMaterialDevice,
    portraits: ShipPortraitLibrary,
    *,
    ocr: OCREngine | None = None,
    max_scrolls: int = 80,
) -> list[TargetShipSnapshot]:
    """Run a target-only, scrollbar-only scan on the verified Cetus device."""
    device.verify_cetus()
    if not _PAUSE_FILE.exists():
        raise TargetInventoryScanError(f'远征暂停文件不存在: {_PAUSE_FILE}')
    adapter = CetusTargetScanDevice(device)
    reader = CetusTargetCardReader(portraits, ocr)
    result = TargetInventoryScanner(adapter, reader).scan_all(max_scrolls=max_scrolls)
    device.verify_cetus()
    return result
