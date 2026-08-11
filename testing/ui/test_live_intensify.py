from pathlib import Path

import cv2
import numpy as np
import pytest

from autowsgr.ui.intensify_workflow import IntensifyWorkflowError
from autowsgr.ui.live_intensify import (
    GridSelectionRef,
    is_intensify_confirmation,
    is_target_selector,
)


_ROOT = Path(r'C:\Users\23264\AppData\Local\Temp\kilo')


def _fixture(name: str) -> np.ndarray:
    path = _ROOT / name
    if not path.exists():
        pytest.skip(f'live intensify fixture unavailable: {path}')
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def test_target_selector_predicate_excludes_material_selector() -> None:
    assert is_target_selector(_fixture('live-target-selector-current.png'))
    assert not is_target_selector(_fixture('live-explicit-material-open.png'))


def test_confirmation_predicate_is_intensify_specific() -> None:
    assert is_intensify_confirmation(_fixture('live-intensify-confirm-dialog.png'))
    assert not is_intensify_confirmation(_fixture('live-explicit-preview.png'))


def test_grid_reference_round_trip_and_validation() -> None:
    expected = GridSelectionRef('scan-57', 12, 1, 3, 0.425, 0.565)
    assert GridSelectionRef.parse(expected.encode('material'), 'material') == expected
    with pytest.raises(IntensifyWorkflowError, match='格式错误'):
        GridSelectionRef.parse(expected.encode('target'), 'material')
