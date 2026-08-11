"""Read-only material inventory scanning from native name-bar bands.

The scanner deliberately avoids portrait matching and card-area gestures.  It
uses the Rust-backed blue name-bar locator, fixed material-grid columns, one
batched OCR call per viewport, and ADB shell taps on the right scrollbar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import adbutils
import cv2
import numpy as np

from autowsgr.constants import SHIPNAMES
from autowsgr.ui.material_first_intensify import (
    MaterialFirstIntensifyController,
    is_material_selector_screen,
)
from autowsgr.ui.utils.ship_list import LEGACY_LIST_WIDTH, to_legacy_format
from autowsgr.vision import apply_ship_patches, get_api_dll
from autowsgr.vision.ocr import OCRResult, _edit_distance, _fuzzy_match


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from autowsgr.emulator.controller import Controller
    from autowsgr.vision import OCREngine


_COLUMN_LEFTS_1920 = (86, 297, 508, 719, 930, 1141, 1352)
_CARD_WIDTH_1920 = 192
_NAME_BAND_MIN_HEIGHT_720 = 12
_NAME_COLOR_BGR = np.asarray(
    ((162, 98, 18), (173, 103, 17), (196, 116, 16)),
    dtype=np.int16,
)
_NAME_COLOR_DISTANCE = 20.0
_MIN_SLOT_BLUE_PIXELS = 80
_PACK_ROW_GAP = 8
_OCR_SCALE = 1.5
_OCR_SLOT_SIZE = (round(_CARD_WIDTH_1920 * _OCR_SCALE), round(42 * _OCR_SCALE))
_OCR_HORIZONTAL_PADDING = 32
_PAUSE_FILE = Path(r'C:\Users\23264\AppData\Local\Temp\kilo\pause-expedition-daemon')


class MaterialInventoryScanError(RuntimeError):
    """Raised when a complete read-only inventory cannot be proven."""


@dataclass(frozen=True, slots=True)
class MaterialViewport:
    """One viewport's ordered ship-name occurrences."""

    names: tuple[str, ...]
    row_lengths: tuple[int, ...]
    bands: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class CapturedMaterialViewport:
    """Geometry-only viewport captured before the single inventory OCR call."""

    crops: tuple[np.ndarray, ...]
    row_lengths: tuple[int, ...]
    bands: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class MaterialInventorySnapshot:
    """A complete material inventory assembled from overlapping viewports."""

    names: tuple[str, ...]
    total: int
    viewport_count: int
    acquisition_method: str = 'native-name-bands+adb-scrollbar'


class NativeLocate(Protocol):
    def __call__(self, image: np.ndarray) -> list[list[int]]: ...


class AdbLosslessMaterialDevice:
    """Minimal ADB-only screenshot/input adapter for material scanning."""

    def __init__(self, serial: str, *, adb_device: object | None = None) -> None:
        if serial != '127.0.0.1:16416':
            raise MaterialInventoryScanError(f'素材扫描只允许 Cetus 设备 127.0.0.1:16416: {serial}')
        self._serial = serial
        self._device = adb_device or adbutils.adb.device(serial=serial)
        self._resolution: tuple[int, int] | None = None

    def screenshot(self) -> np.ndarray:
        image = self._device.screenshot(error_ok=False).convert('RGB')
        return np.asarray(image, dtype=np.uint8)

    def shell(self, command: str) -> str:
        result = self._device.shell(command)
        return result if isinstance(result, str) else str(result)

    @property
    def resolution(self) -> tuple[int, int]:
        if self._resolution is None:
            size = self._device.window_size()
            self._resolution = (int(size[0]), int(size[1]))
        return self._resolution

    def click(self, x: float, y: float, *, delay: bool = True) -> None:
        width, height = self.resolution
        px = min(width - 1, max(0, round(x * width)))
        py = min(height - 1, max(0, round(y * height)))
        self._device.shell(f'input tap {px} {py}')
        if delay:
            time.sleep(0.3)

    def verify_cetus(self) -> None:
        product = self.shell('getprop ro.product.name').strip()
        model = self.shell('getprop ro.product.model').strip()
        if product != 'Cetus' or model != 'CET-AL00':
            raise MaterialInventoryScanError(f'设备身份不匹配: product={product}, model={model}')
        if not _PAUSE_FILE.exists():
            raise MaterialInventoryScanError(f'远征暂停文件不存在: {_PAUSE_FILE}')


def _name_blue_mask(image_rgb: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR).astype(np.int16)
    distances = np.linalg.norm(bgr[:, :, None, :] - _NAME_COLOR_BGR[None, None, :, :], axis=3)
    return np.min(distances, axis=2) < _NAME_COLOR_DISTANCE


def _normalize_ocr_name(result: OCRResult, candidates: list[str] | None = None) -> str | None:
    text = apply_ship_patches(result.text.strip())
    pool = candidates or SHIPNAMES
    if not text:
        return None
    direct = _fuzzy_match(text, pool)
    if direct is not None or len(text) < 3:
        return direct
    affix_matches = {
        name
        for name in pool
        if len(name) > len(text)
        and (
            _edit_distance(text, name[: len(text)]) <= 1
            or _edit_distance(text, name[-len(text) :]) <= 1
        )
    }
    return next(iter(affix_matches)) if len(affix_matches) == 1 else None


class MaterialViewportReader:
    """Convert one material-selector screenshot into an ordered name sequence."""

    def __init__(self, ocr: OCREngine, *, locate: NativeLocate | None = None) -> None:
        self._ocr = ocr
        self._locate = locate or get_api_dll().locate

    def locate_name_bands(self, screen: np.ndarray) -> tuple[tuple[int, int], ...]:
        """Return native-resolution y bands, filtering thin native-locator noise."""
        bgr_720p, scale_y, _scale_x = to_legacy_format(screen)
        raw = self._locate(bgr_720p[:, :LEGACY_LIST_WIDTH])
        bands: list[tuple[int, int]] = []
        previous_bottom = -1
        for top, bottom in raw:
            if bottom - top < _NAME_BAND_MIN_HEIGHT_720:
                continue
            if bottom - top > 45 or top < previous_bottom:
                raise MaterialInventoryScanError(f'native 舰名蓝条几何异常: {raw}')
            native_top = max(0, round(top * scale_y))
            native_bottom = min(screen.shape[0], round(bottom * scale_y))
            if native_bottom > native_top:
                bands.append((native_top, native_bottom))
                previous_bottom = bottom
        return tuple(bands)

    @staticmethod
    def _column_bounds(width: int) -> tuple[tuple[int, int], ...]:
        scale = width / 1920
        return tuple(
            (round(left * scale), round((left + _CARD_WIDTH_1920) * scale))
            for left in _COLUMN_LEFTS_1920
        )

    def _present_slots(
        self,
        screen: np.ndarray,
        bands: Sequence[tuple[int, int]],
    ) -> tuple[list[tuple[int, int, int, int, int, int]], tuple[int, ...]]:
        columns = self._column_bounds(screen.shape[1])
        blue = _name_blue_mask(screen)
        slots: list[tuple[int, int, int, int, int, int]] = []
        row_lengths: list[int] = []
        pixel_scale = screen.shape[0] * screen.shape[1] / (1080 * 1920)
        threshold = max(20, round(_MIN_SLOT_BLUE_PIXELS * pixel_scale))
        for row, (top, bottom) in enumerate(bands):
            present = 0
            saw_empty = False
            for column, (left, right) in enumerate(columns):
                exists = int(np.count_nonzero(blue[top:bottom, left:right])) >= threshold
                if not exists:
                    saw_empty = True
                    continue
                if saw_empty:
                    raise MaterialInventoryScanError('同一舰名行出现非连续卡位，无法证明几何顺序')
                slots.append((row, column, left, top, right, bottom))
                present += 1
            if present:
                row_lengths.append(present)
            else:
                raise MaterialInventoryScanError(f'native 舰名蓝条 {row} 没有固定列卡位证据')
        return slots, tuple(row_lengths)

    @staticmethod
    def _pack_rows(
        screen: np.ndarray,
        bands: Sequence[tuple[int, int]],
    ) -> tuple[np.ndarray, tuple[tuple[int, int], ...]]:
        if not bands:
            return np.zeros((1, 1, 3), dtype=np.uint8), ()
        list_width = round(screen.shape[1] * LEGACY_LIST_WIDTH / 1280)
        heights = [bottom - top for top, bottom in bands]
        canvas_height = sum(heights) + _PACK_ROW_GAP * (len(bands) - 1)
        canvas = np.zeros((canvas_height, list_width, 3), dtype=np.uint8)
        packed: list[tuple[int, int]] = []
        cursor = 0
        for top, bottom in bands:
            height = bottom - top
            canvas[cursor : cursor + height] = screen[top:bottom, :list_width]
            packed.append((cursor, cursor + height))
            cursor += height + _PACK_ROW_GAP
        return canvas, tuple(packed)

    def capture(self, screen: np.ndarray) -> CapturedMaterialViewport:
        bands = self.locate_name_bands(screen)
        if not bands:
            raise MaterialInventoryScanError('当前视口未定位到任何舰名蓝条')
        slots, _row_lengths = self._present_slots(screen, bands)
        if not slots:
            raise MaterialInventoryScanError('舰名蓝条中没有固定列卡位证据')

        row_crops: list[list[np.ndarray]] = [[] for _band in bands]
        for row, _column, left, top, right, bottom in slots:
            crop = cv2.resize(
                screen[top:bottom, left:right],
                _OCR_SLOT_SIZE,
                interpolation=cv2.INTER_CUBIC,
            )
            background = tuple(int(value) for value in np.median(crop, axis=(0, 1)))
            padded = cv2.copyMakeBorder(
                crop,
                0,
                0,
                _OCR_HORIZONTAL_PADDING,
                _OCR_HORIZONTAL_PADDING,
                cv2.BORDER_CONSTANT,
                value=background,
            )
            hsv = cv2.cvtColor(padded, cv2.COLOR_RGB2HSV)
            text_mask = ((hsv[:, :, 1] < 105) & (hsv[:, :, 2] > 150)).astype(np.uint8) * 255
            text_mask = cv2.morphologyEx(
                text_mask,
                cv2.MORPH_OPEN,
                np.ones((2, 2), dtype=np.uint8),
            )
            text_only = np.full_like(padded, 255)
            text_only[text_mask > 0] = 0
            row_crops[row].append(text_only)

        complete_crops: list[np.ndarray] = []
        complete_lengths: list[int] = []
        complete_bands: list[tuple[int, int]] = []
        for band, crops in zip(bands, row_crops, strict=True):
            greys = [cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) for crop in crops]
            edge_margin = 3
            touches_top = all(np.any(grey[:edge_margin] < 80) for grey in greys)
            touches_bottom = all(np.any(grey[-edge_margin:] < 80) for grey in greys)
            if touches_top or touches_bottom:
                continue
            complete_crops.extend(crops)
            complete_lengths.append(len(crops))
            complete_bands.append(band)
        if not complete_crops:
            raise MaterialInventoryScanError('当前视口没有完整可见舰名蓝条')
        return CapturedMaterialViewport(
            tuple(complete_crops),
            tuple(complete_lengths),
            tuple(complete_bands),
        )

    def capture_best(
        self,
        screens: Sequence[np.ndarray],
    ) -> CapturedMaterialViewport:
        """Keep the most text-rich name-bar crop from geometry-identical frames."""
        captures = tuple(self.capture(screen) for screen in screens)
        geometry = (captures[0].row_lengths, captures[0].bands)
        if any((capture.row_lengths, capture.bands) != geometry for capture in captures[1:]):
            raise MaterialInventoryScanError('稳定帧之间的舰名栏几何不一致')

        def text_score(crop: np.ndarray) -> int:
            grey = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
            return int(np.count_nonzero(grey < 80))

        crops = tuple(
            max((capture.crops[index] for capture in captures), key=text_score)
            for index in range(len(captures[0].crops))
        )
        return CapturedMaterialViewport(crops, *geometry)

    def recognize_captures(
        self,
        captures: Sequence[CapturedMaterialViewport],
    ) -> tuple[MaterialViewport, ...]:
        crops = [crop for capture in captures for crop in capture.crops]
        batch_results = self._ocr.recognize_batch(crops)
        if len(batch_results) != len(crops):
            raise MaterialInventoryScanError('批量 OCR 返回数量与舰名栏数量不一致')
        viewports: list[MaterialViewport] = []
        cursor = 0
        for capture in captures:
            count = len(capture.crops)
            viewport_results = batch_results[cursor : cursor + count]
            cursor += count
            names = self._normalize_results(viewport_results)
            viewports.append(MaterialViewport(names, capture.row_lengths, capture.bands))
        return tuple(viewports)

    @staticmethod
    def _normalize_results(batch_results: Sequence[Sequence[OCRResult]]) -> tuple[str, ...]:
        normalized: list[str | None] = []
        for index, results in enumerate(batch_results):
            if not results:
                raise MaterialInventoryScanError(f'舰名栏 {index} 没有 OCR 结果')
            result = max(results, key=lambda item: item.confidence)
            if not result.text.strip():
                raise MaterialInventoryScanError(f'舰名栏 {index} 无法唯一 OCR 归一化')
            normalized.append(_normalize_ocr_name(result))
        for index, name in enumerate(normalized):
            if name is None:
                result = max(batch_results[index], key=lambda item: item.confidence)
                raise MaterialInventoryScanError(
                    f'舰名栏 {index} 无法唯一 OCR 归一化: raw={result.text!r}, '
                    f'confidence={result.confidence:.3f}'
                )
        return tuple(normalized)  # type: ignore[return-value]

    def read(self, screen: np.ndarray) -> MaterialViewport:
        return self.recognize_captures((self.capture(screen),))[0]


def merge_viewport_names(
    accumulated: Sequence[str],
    current: Sequence[str],
    *,
    minimum_overlap: int = 7,
) -> tuple[tuple[str, ...], int]:
    """Merge by the longest accumulated suffix/current prefix overlap."""
    left = tuple(accumulated)
    right = tuple(current)
    if not left:
        return right, 0
    maximum = min(len(left), len(right))
    overlap = next(
        (size for size in range(maximum, 0, -1) if left[-size:] == right[:size]),
        0,
    )
    if overlap < minimum_overlap:
        raise MaterialInventoryScanError('相邻素材视口无法建立舰名序列衔接')
    return left + right[overlap:], overlap


class AdbScrollbarStepper:
    """Move only through an Android-side short drag inside the scrollbar thumb."""

    def __init__(self, ctrl: Controller, *, x: int = 1580, step_pixels: int = 11) -> None:
        self._ctrl = ctrl
        self._x = x
        self._step_pixels = step_pixels

    def thumb_bounds(self, screen: np.ndarray) -> tuple[int, int]:
        """Locate the light-grey scrollbar thumb on its fixed vertical track."""
        height, width = screen.shape[:2]
        x = min(width - 1, round(self._x * width / 1920))
        column = screen[:, x].astype(np.int16)
        # Lossless Cetus fixtures show the thumb as nearly-neutral RGB 184-187,
        # while the underlying track is dark grey around RGB 65-80.
        neutral = np.max(column, axis=1) - np.min(column, axis=1) <= 8
        light = np.min(column, axis=1) >= 160
        track_top = round(0.12 * height)
        track_bottom = round(1034 * height / 1080)
        mask = neutral & light
        mask[:track_top] = False
        mask[track_bottom:] = False
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for y, present in enumerate(mask):
            if present and start is None:
                start = y
            elif not present and start is not None:
                minimum = 150 if y == track_bottom else 250
                if y - start >= round(minimum * height / 1080):
                    runs.append((start, y))
                start = None
        if start is not None and track_bottom - start >= round(150 * height / 1080):
            runs.append((start, track_bottom))
        if len(runs) != 1:
            raise MaterialInventoryScanError(f'滚动条滑块定位不唯一: {runs}')
        return runs[0]

    def thumb_bottom(self, screen: np.ndarray) -> int:
        return self.thumb_bounds(screen)[1]

    def is_top(self, screen: np.ndarray) -> bool:
        top, _bottom = self.thumb_bounds(screen)
        return top <= round(140 * screen.shape[0] / 1080)

    def is_bottom(self, screen: np.ndarray) -> bool:
        _top, bottom = self.thumb_bounds(screen)
        return bottom >= round(1024 * screen.shape[0] / 1080)

    def advance(self, *, thumb_bottom: int, screen_height: int) -> None:
        half_thumb = round(142 * screen_height / 1080)
        start_y = max(round(130 * screen_height / 1080), thumb_bottom - half_thumb)
        end_y = min(screen_height - 1, start_y + self._step_pixels)
        x = round(self._x * self._ctrl.resolution[0] / 1920)
        step = max(1, round(self._step_pixels * screen_height / 1080))
        end_y = min(screen_height - 1, start_y + step)
        self._ctrl.shell(f'input swipe {x} {start_y} {x} {end_y} 300')


def has_selected_material(screen: np.ndarray) -> bool:
    """Detect the large bright-blue sequence badge drawn over a selected card."""
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array((90, 130, 120)), np.array((115, 255, 255)))
    height, width = screen.shape[:2]
    mask[:, round(width * 0.81) :] = 0
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask)
    minimum_area = round(1200 * height * width / (1080 * 1920))
    maximum_area = round(6000 * height * width / (1080 * 1920))
    candidates: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, component_width, component_height, area = map(int, stats[index])
        if (
            minimum_area <= area <= maximum_area
            and round(35 * width / 1920) <= component_width <= round(110 * width / 1920)
            and round(35 * height / 1080) <= component_height <= round(110 * height / 1080)
            and 0.55 <= component_width / component_height <= 1.8
            and area / (component_width * component_height) >= 0.35
            and y < round(0.90 * height)
        ):
            candidates.append((x, y, component_width, component_height))
    if not candidates:
        return False
    card_pitch = round(211 * width / 1920)
    y_tolerance = round(5 * height / 1080)
    for x, y, _component_width, _component_height in candidates:
        repeated = any(
            abs(other_y - y) <= y_tolerance
            and abs(abs(other_x - x) - card_pitch) <= round(5 * width / 1920)
            for other_x, other_y, _other_width, _other_height in candidates
        )
        if not repeated:
            return True
    return False


class MaterialInventoryScanner:
    """Assemble a complete inventory from overlapping read-only viewports."""

    def __init__(
        self,
        ctrl: Controller,
        reader: MaterialViewportReader,
        stepper: AdbScrollbarStepper,
        *,
        is_material_screen: Callable[[np.ndarray], bool] = is_material_selector_screen,
        stagnant_limit: int = 2,
        settle_seconds: float = 0.8,
        sample_count: int = 8,
        sample_interval_seconds: float = 0.65,
    ) -> None:
        self._ctrl = ctrl
        self._reader = reader
        self._stepper = stepper
        self._is_material_screen = is_material_screen
        self._stagnant_limit = stagnant_limit
        self._settle_seconds = settle_seconds
        if sample_count < 2:
            raise ValueError('素材视口至少需要采样两帧')
        self._sample_count = sample_count
        self._sample_interval_seconds = sample_interval_seconds

    def _stable_screens(self) -> tuple[np.ndarray, ...]:
        screens: list[np.ndarray] = []
        thumb_bounds: tuple[int, int] | None = None
        for index in range(self._sample_count):
            screen = self._ctrl.screenshot()
            if not self._is_material_screen(screen) or has_selected_material(screen):
                raise MaterialInventoryScanError('素材页面状态不安全或已有素材被选中')
            current_thumb = self._stepper.thumb_bounds(screen)
            if thumb_bounds is None:
                thumb_bounds = current_thumb
            elif current_thumb != thumb_bounds:
                raise MaterialInventoryScanError('多帧采样期间滚动条位置发生变化')
            screens.append(screen)
            if index + 1 < self._sample_count:
                time.sleep(self._sample_interval_seconds)
        return tuple(screens)

    def scan(self, *, max_viewports: int = 24) -> MaterialInventorySnapshot:
        captures: list[CapturedMaterialViewport] = []
        previous_thumb: int | None = None
        stagnant = 0
        for viewport_count in range(1, max_viewports + 1):
            stable_screens = self._stable_screens()
            screen = stable_screens[-1]
            if viewport_count == 1 and not self._stepper.is_top(screen):
                raise MaterialInventoryScanError('素材扫描必须从滚动条顶部开始')
            captures.append(self._reader.capture_best(stable_screens))
            thumb = self._stepper.thumb_bottom(screen)
            no_thumb_move = previous_thumb is not None and thumb == previous_thumb
            at_bottom = self._stepper.is_bottom(screen)
            if no_thumb_move and not at_bottom:
                raise MaterialInventoryScanError('滚动条在未到底时没有移动')
            stagnant = stagnant + 1 if at_bottom and no_thumb_move else 0
            if stagnant >= self._stagnant_limit:
                viewports = self._reader.recognize_captures(captures)
                accumulated: tuple[str, ...] = ()
                for viewport in viewports:
                    accumulated, _overlap = merge_viewport_names(
                        accumulated,
                        viewport.names,
                        minimum_overlap=max(viewport.row_lengths),
                    )
                return MaterialInventorySnapshot(accumulated, len(accumulated), viewport_count)
            self._stepper.advance(thumb_bottom=thumb, screen_height=screen.shape[0])
            time.sleep(self._settle_seconds)
            previous_thumb = thumb
        raise MaterialInventoryScanError(f'超过最大视口数 {max_viewports}，无法证明素材列表到底')


def scan_material_inventory_from_main(
    device: AdbLosslessMaterialDevice,
    ocr: OCREngine,
    *,
    max_viewports: int = 24,
) -> MaterialInventorySnapshot:
    """Navigate from main to the material selector, then perform a read-only scan."""
    device.verify_cetus()
    MaterialFirstIntensifyController(device).enter_material_selector_from_main()
    reader = MaterialViewportReader(ocr)
    stepper = AdbScrollbarStepper(device)
    scanner = MaterialInventoryScanner(device, reader, stepper)
    snapshot = scanner.scan(max_viewports=max_viewports)
    device.verify_cetus()
    return snapshot
