from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from autowsgr.ui.live_target_inventory import (
    CetusTargetCardReader,
    _is_cross,
    _topology_digit,
    target_thumb_bounds,
)


_ROOT = Path(r'C:\Users\23264\AppData\Local\Temp\kilo')


def test_target_thumb_supports_short_live_thumb() -> None:
    path = _ROOT / 'live-target-selector-current.png'
    if path.exists():
        screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    else:
        screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        screen[135:260, 1580] = (192, 193, 195)
    assert target_thumb_bounds(screen) == (135, 260)


def test_saved_chitose_stat_glyphs_distinguish_one_cross_zero_and_other() -> None:
    paths = [_ROOT / f'target-strength-tight-{index}.png' for index in range(4)]
    if not all(path.exists() for path in paths):
        return
    crops = [cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB) for path in paths]
    assert _topology_digit(crops[0]) == 1
    assert _is_cross(crops[1])
    assert _topology_digit(crops[2]) is None
    assert _topology_digit(crops[3]) is None


class _NoPortraits:
    def identify(self, _image: np.ndarray) -> None:
        return None


class _FallbackOcr:
    def __init__(self) -> None:
        self.values = iter((3, 8))

    def recognize_number(self, _image: np.ndarray) -> int:
        return next(self.values)


def test_reader_recovers_saved_chitose_strength_vector() -> None:
    paths = [_ROOT / f'target-strength-tight-{index}.png' for index in range(4)]
    if not all(path.exists() for path in paths):
        return
    reader = CetusTargetCardReader(_NoPortraits(), _FallbackOcr())  # type: ignore[arg-type]
    crops = [cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB) for path in paths]
    values = [reader._read_stat(crop) for crop in crops]
    assert values == [1, 0, 3, 8]
