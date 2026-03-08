"""选船列表 DLL 行定位 + OCR 识别。

从 ``autowsgr.ui.decisive.fleet_ocr`` 中提取的公用函数，
普通出征换船和决战换船均可使用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2

from autowsgr.infra.logger import get_logger


if TYPE_CHECKING:
    import numpy as np

    from autowsgr.vision import OCREngine


_log = get_logger('ui')

#: Legacy 标准分辨率 (DLL 校准基准)
LEGACY_WIDTH: int = 1280
LEGACY_HEIGHT: int = 720

#: Legacy 选船列表左侧裁剪宽度 (px@1280)
LEGACY_LIST_WIDTH: int = 1048


def to_legacy_format(screen: np.ndarray) -> tuple[np.ndarray, float, float]:
    """将 V2 截图转为 DLL 所需的 legacy 格式。

    DLL 内部基于 1280x720 BGR 图像校准，V2 ``screenshot()``
    返回模拟器原生分辨率的 RGB 图像，需做两步转换。

    Returns
    -------
    tuple[np.ndarray, float, float]
        ``(bgr_720p, scale_y, scale_x)``
        -- bgr_720p: 1280x720 BGR 图像
        -- scale_y / scale_x: legacy 坐标 -> 原始坐标的缩放比
    """
    h, w = screen.shape[:2]
    scale_y = h / LEGACY_HEIGHT
    scale_x = w / LEGACY_WIDTH
    resized = cv2.resize(screen, (LEGACY_WIDTH, LEGACY_HEIGHT))
    bgr = cv2.cvtColor(resized, cv2.COLOR_RGB2BGR)
    return bgr, scale_y, scale_x


def locate_ship_rows(
    ocr: OCREngine,
    screen: np.ndarray,
) -> list[tuple[str, float, float]]:
    """在选船列表页用 DLL 定位舰船名行，再逐行 OCR 识别。

    其他场景 (如 ``_click_ship_in_list``, ``recognize_ships_in_list``)
    应复用此函数而非重复实现 OCR 逻辑。

    对齐 legacy ``recognize_ship``:

    1. resize + RGB->BGR 转为 1280x720 BGR (DLL 校准基准)
    2. 裁剪左侧 1048px (与 legacy ``screen[:, :1048]`` 一致)
    3. ``dll.locate()`` 定位行区域
    4. 将行坐标映射回原始分辨率, 在原图上裁剪并 OCR

    Parameters
    ----------
    ocr:
        OCR 引擎实例。
    screen:
        选船列表页面的 V2 截图 (RGB, 任意分辨率)。

    Returns
    -------
    list[tuple[str, float, float]]
        ``(ship_name, cx_rel, cy_rel)`` 列表 -- 舰船名及其行中心
        相对于 **完整截图** 的归一化坐标。
    """
    from autowsgr.constants import SHIPNAMES
    from autowsgr.vision import get_api_dll
    from autowsgr.vision.ocr import _fuzzy_match

    h, w = screen.shape[:2]

    # 转为 legacy 格式 (1280x720, BGR)
    bgr_720p, scale_y, scale_x = to_legacy_format(screen)
    list_720p = bgr_720p[:, :LEGACY_LIST_WIDTH]  # legacy 裁剪宽度

    dll = get_api_dll()
    rows = dll.locate(list_720p)
    _log.debug('[选船列表] DLL 定位到 {} 行候选项', len(rows))

    # 在原始分辨率上裁剪并 OCR (用原图的左 82% 区域)
    list_w_native = int(w * LEGACY_LIST_WIDTH / LEGACY_WIDTH)
    list_area_native = screen[:, :list_w_native]

    found: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for y_start_720, y_end_720 in rows:
        # 将 720p 坐标映射回原始分辨率
        y_start = max(0, int((y_start_720 - 1) * scale_y))
        y_end = min(h, int((y_end_720 + 1) * scale_y))

        row_img = list_area_native[y_start:y_end]

        # 对齐 legacy: recognize(multiple=True) -- 同一 DLL 行可含多个舰船名
        results = ocr.recognize(row_img)
        for r in results:
            text = r.text.strip()
            if not text:
                continue
            name = _fuzzy_match(text, SHIPNAMES)
            if name is None or name in seen:
                continue
            seen.add(name)
            # 从 bbox 计算精确位置 (bbox 相对于 row_img)
            if r.bbox is not None:
                x1, y1, x2, y2 = r.bbox
                cx = (x1 + x2) / 2 / w
                cy = (y_start + (y1 + y2) / 2) / h
            else:
                cx = list_w_native / 2 / w
                cy = (y_start + y_end) / 2 / h
            found.append((name, cx, cy))

    _log.debug(
        '[选船列表] 识别: {} (共 {} 行)',
        sorted({n for n, _, _ in found}),
        len(rows),
    )
    return found


def recognize_ships_in_list(
    ocr: OCREngine,
    screen: np.ndarray,
) -> set[str]:
    """识别选船列表页面中的所有可见舰船名 (去重集合)。

    基于 :func:`locate_ship_rows` 的薄封装。
    """
    return {name for name, _, _ in locate_ship_rows(ocr, screen)}
