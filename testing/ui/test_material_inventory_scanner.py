from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from autowsgr.ui.material_inventory_scanner import (
    AdbLosslessMaterialDevice,
    AdbScrollbarStepper,
    CapturedMaterialViewport,
    MaterialInventoryScanError,
    MaterialInventoryScanner,
    MaterialViewportReader,
    _normalize_ocr_name,
    merge_viewport_names,
    scan_material_inventory_from_main,
)
from autowsgr.vision.ocr import OCRResult


_FIXTURE_ROOT = Path(r'C:\Users\23264\AppData\Local\Temp\kilo\live-material-rebuild')


def _fixture(name: str) -> np.ndarray:
    path = _FIXTURE_ROOT / name
    if not path.exists():
        pytest.skip(f'local lossless material fixture not available: {path}')
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def _material_screen(*, row_columns: tuple[int, ...] = (7, 7)) -> np.ndarray:
    screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
    name_color = (18, 98, 162)
    row_tops = (520, 952)
    for row, columns in enumerate(row_columns):
        for column in range(columns):
            left = 86 + column * 211
            screen[row_tops[row] : row_tops[row] + 42, left : left + 192] = name_color
    return screen


def test_viewport_reader_uses_native_bands_and_one_ocr_call() -> None:
    ocr = MagicMock()
    ocr.recognize_batch.return_value = [
        [OCRResult('霞飞', 0.99)],
        [OCRResult('企业', 0.99)],
        [OCRResult('U-96', 0.99)],
    ]
    locate = MagicMock(return_value=[[346, 374], [634, 662], [663, 664]])
    reader = MaterialViewportReader(ocr, locate=locate)

    viewport = reader.read(_material_screen(row_columns=(2, 1)))

    assert viewport.names == ('霞飞', '企业', 'U-96')
    assert viewport.row_lengths == (2, 1)
    locate.assert_called_once()
    assert locate.call_args.args[0].shape == (720, 1048, 3)
    assert ocr.recognize_batch.call_count == 1
    assert [image.shape for image in ocr.recognize_batch.call_args.args[0]] == [
        (63, 352, 3),
        (63, 352, 3),
        (63, 352, 3),
    ]


def test_capture_best_selects_text_richer_crop_per_slot() -> None:
    reader = MaterialViewportReader(MagicMock())
    sparse = np.full((63, 352, 3), 255, dtype=np.uint8)
    rich = sparse.copy()
    rich[20:40, 80:180] = 0
    reader.capture = MagicMock(
        side_effect=[
            CapturedMaterialViewport((sparse,), (1,), ((10, 20),)),
            CapturedMaterialViewport((rich,), (1,), ((10, 20),)),
        ]
    )

    capture = reader.capture_best((MagicMock(), MagicMock()))

    assert capture.crops[0] is rich


def test_capture_excludes_rows_whose_text_is_clipped_at_vertical_edge() -> None:
    screen = _material_screen(row_columns=(2, 2))
    screen[519:526, 120:170] = 255
    screen[519:526, 331:381] = 255
    screen[970:976, 120:170] = 255
    screen[970:976, 331:381] = 255
    reader = MaterialViewportReader(
        MagicMock(),
        locate=lambda _image: [[346, 374], [634, 662]],
    )

    capture = reader.capture(screen)

    assert capture.row_lengths == (2,)
    assert capture.bands == ((951, 993),)
    assert len(capture.crops) == 2


def test_capture_best_rejects_geometry_change_between_frames() -> None:
    reader = MaterialViewportReader(MagicMock())
    crop = np.zeros((63, 352, 3), dtype=np.uint8)
    reader.capture = MagicMock(
        side_effect=[
            CapturedMaterialViewport((crop,), (1,), ((10, 20),)),
            CapturedMaterialViewport((crop,), (1,), ((11, 21),)),
        ]
    )

    with pytest.raises(MaterialInventoryScanError, match='几何不一致'):
        reader.capture_best((MagicMock(), MagicMock()))


def test_viewport_reader_rejects_unrecognized_present_name_slot() -> None:
    ocr = MagicMock(return_value=[])
    ocr.recognize_batch.return_value = [[]]
    reader = MaterialViewportReader(ocr, locate=lambda _image: [[346, 374]])

    with pytest.raises(MaterialInventoryScanError, match='舰名栏'):
        reader.read(_material_screen(row_columns=(1,)))


def test_viewport_reader_rejects_ambiguous_overlap_even_with_history() -> None:
    ocr = MagicMock()
    ocr.recognize_batch.return_value = [
        [OCRResult('企业', 0.99)],
        [OCRResult('晓仙', 0.80)],
        [OCRResult('U-96', 0.99)],
    ]
    reader = MaterialViewportReader(
        ocr,
        locate=lambda _image: [[346, 374], [634, 662]],
    )

    with pytest.raises(MaterialInventoryScanError, match='舰名栏'):
        reader.read(
            _material_screen(row_columns=(2, 1)),
        )
    assert ocr.recognize_batch.call_count == 1


def test_unique_long_ship_suffix_allows_one_ocr_error() -> None:
    assert _normalize_ocr_name(OCRResult('维内特', 0.9)) == '维托里奥·维内托'


def test_unique_long_ship_prefix_handles_scrolling_name_bar() -> None:
    assert _normalize_ocr_name(OCRResult('。安德烈', 0.9)) == '安德烈亚·多利亚'


def test_short_or_ambiguous_suffix_is_not_guessed() -> None:
    assert _normalize_ocr_name(OCRResult('企业', 0.9)) == '企业'
    assert (
        _normalize_ocr_name(
            OCRResult('维内特', 0.9),
            ['甲·维内托', '乙·维内托'],
        )
        is None
    )


def test_real_fixture_native_bands_filter_one_pixel_noise() -> None:
    screen = _fixture('rebuild-top-03.png')
    reader = MaterialViewportReader(MagicMock())

    assert reader.locate_name_bands(screen) == ((276, 316), (708, 748))


def test_native_band_geometry_rejects_overlap_or_excessive_height() -> None:
    screen = _material_screen(row_columns=(1,))
    with pytest.raises(MaterialInventoryScanError, match='几何异常'):
        MaterialViewportReader(MagicMock(), locate=lambda _image: [[100, 150]]).locate_name_bands(
            screen
        )
    with pytest.raises(MaterialInventoryScanError, match='几何异常'):
        MaterialViewportReader(
            MagicMock(),
            locate=lambda _image: [[100, 130], [120, 150]],
        ).locate_name_bands(screen)


def test_overlap_merge_preserves_duplicate_occurrences() -> None:
    accumulated = ('A', 'A', 'B', 'C')
    current = ('B', 'C', 'C', 'D')

    merged, overlap = merge_viewport_names(accumulated, current, minimum_overlap=2)

    assert overlap == 2
    assert merged == ('A', 'A', 'B', 'C', 'C', 'D')


def test_overlap_merge_rejects_disconnected_viewport() -> None:
    with pytest.raises(MaterialInventoryScanError, match='衔接'):
        merge_viewport_names(('A', 'B'), ('C', 'D'), minimum_overlap=2)


def test_adb_stepper_only_drags_inside_right_scrollbar_thumb() -> None:
    ctrl = MagicMock()
    ctrl.resolution = (1920, 1080)
    stepper = AdbScrollbarStepper(ctrl, x=1580, step_pixels=11)

    stepper.advance(thumb_bottom=440, screen_height=1080)

    ctrl.shell.assert_called_once_with('input swipe 1580 298 1580 309 300')


@pytest.mark.parametrize(
    ('fixture', 'expected_bottom'),
    [
        ('rebuild-top-04.png', 420),
        ('rebuild-top-03.png', 571),
        ('rebuild-top-02.png', 722),
        ('rebuild-top-01.png', 874),
        ('rebuild-top-00.png', 1025),
        ('rebuild-bottom-scrollbar.png', 1034),
    ],
)
def test_adb_stepper_locates_real_scrollbar_thumb_bottom(
    fixture: str,
    expected_bottom: int,
) -> None:
    screen = _fixture(fixture)

    assert AdbScrollbarStepper(MagicMock()).thumb_bottom(screen) == expected_bottom


def test_scanner_merges_views_and_stops_after_stagnation() -> None:
    ctrl = MagicMock()
    ctrl.screenshot.side_effect = [np.zeros((10, 10, 3), dtype=np.uint8)] * 6
    reader = MagicMock()
    reader.capture_best.side_effect = [MagicMock(), MagicMock(), MagicMock()]
    reader.recognize_captures.return_value = [
        MagicMock(names=('A', 'B', 'C'), row_lengths=(3,)),
        MagicMock(names=('B', 'C', 'D'), row_lengths=(2,)),
        MagicMock(names=('B', 'C', 'D'), row_lengths=(2,)),
    ]
    stepper = MagicMock()
    stepper.thumb_bottom.side_effect = [100, 200, 200]
    stepper.is_top.return_value = True
    stepper.is_bottom.side_effect = [False, True, True]
    scanner = MaterialInventoryScanner(
        ctrl,
        reader,
        stepper,
        is_material_screen=lambda _screen: True,
        stagnant_limit=1,
        settle_seconds=0,
        sample_count=2,
        sample_interval_seconds=0,
    )

    snapshot = scanner.scan(max_viewports=5)

    assert snapshot.names == ('A', 'B', 'C', 'D')
    assert snapshot.total == 4
    assert snapshot.viewport_count == 3
    assert stepper.advance.call_count == 2
    reader.recognize_captures.assert_called_once()


def test_scanner_samples_multiple_frames_per_scroll_position() -> None:
    ctrl = MagicMock()
    ctrl.screenshot.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    reader = MagicMock()
    reader.capture_best.return_value = MagicMock()
    reader.recognize_captures.return_value = [
        MagicMock(names=('A', 'B'), row_lengths=(2,)),
        MagicMock(names=('A', 'B'), row_lengths=(2,)),
    ]
    stepper = MagicMock()
    stepper.thumb_bounds.return_value = (10, 20)
    stepper.thumb_bottom.return_value = 20
    stepper.is_top.return_value = True
    stepper.is_bottom.return_value = True
    scanner = MaterialInventoryScanner(
        ctrl,
        reader,
        stepper,
        is_material_screen=lambda _screen: True,
        stagnant_limit=1,
        settle_seconds=0,
        sample_count=5,
        sample_interval_seconds=0,
    )

    scanner.scan(max_viewports=2)

    assert ctrl.screenshot.call_count == 10
    assert all(len(call.args[0]) == 5 for call in reader.capture_best.call_args_list)


def test_all_captured_viewports_use_one_inventory_ocr_call() -> None:
    ocr = MagicMock()
    ocr.recognize_batch.return_value = [
        [OCRResult('霞飞', 0.99)],
        [OCRResult('企业', 0.99)],
        [OCRResult('企业', 0.99)],
        [OCRResult('U-96', 0.99)],
    ]
    reader = MaterialViewportReader(ocr, locate=MagicMock())
    crop = np.zeros((63, 352, 3), dtype=np.uint8)
    captures = (
        CapturedMaterialViewport((crop, crop), (2,), ((1, 2),)),
        CapturedMaterialViewport((crop, crop), (2,), ((3, 4),)),
    )

    viewports = reader.recognize_captures(captures)

    assert [viewport.names for viewport in viewports] == [
        ('霞飞', '企业'),
        ('企业', 'U-96'),
    ]
    ocr.recognize_batch.assert_called_once()
    assert len(ocr.recognize_batch.call_args.args[0]) == 4


def test_scanner_fails_before_input_when_page_is_unknown() -> None:
    ctrl = MagicMock()
    ctrl.screenshot.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    stepper = MagicMock()
    scanner = MaterialInventoryScanner(
        ctrl,
        MagicMock(),
        stepper,
        is_material_screen=lambda _screen: False,
    )

    with pytest.raises(MaterialInventoryScanError, match='素材页面状态不安全'):
        scanner.scan()

    stepper.advance.assert_not_called()


def test_scanner_rejects_non_top_initial_viewport() -> None:
    ctrl = MagicMock()
    ctrl.screenshot.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    stepper = MagicMock()
    stepper.is_top.return_value = False
    scanner = MaterialInventoryScanner(
        ctrl,
        MagicMock(),
        stepper,
        is_material_screen=lambda _screen: True,
        settle_seconds=0,
        sample_count=2,
        sample_interval_seconds=0,
    )

    with pytest.raises(MaterialInventoryScanError, match='顶部开始'):
        scanner.scan()

    stepper.advance.assert_not_called()


def test_scanner_rejects_stuck_scrollbar_before_bottom() -> None:
    ctrl = MagicMock()
    ctrl.screenshot.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
    reader = MagicMock()
    reader.capture_best.side_effect = [MagicMock(), MagicMock()]
    reader.recognize_captures.return_value = [
        MagicMock(names=('A', 'B', 'C'), row_lengths=(3,)),
        MagicMock(names=('B', 'C', 'D'), row_lengths=(2,)),
    ]
    stepper = MagicMock()
    stepper.is_top.return_value = True
    stepper.is_bottom.return_value = False
    stepper.thumb_bottom.side_effect = [100, 100]
    scanner = MaterialInventoryScanner(
        ctrl,
        reader,
        stepper,
        is_material_screen=lambda _screen: True,
        settle_seconds=0,
        sample_count=2,
        sample_interval_seconds=0,
    )

    with pytest.raises(MaterialInventoryScanError, match='未到底时没有移动'):
        scanner.scan()


def test_single_name_overlap_is_not_sufficient() -> None:
    with pytest.raises(MaterialInventoryScanError, match='衔接'):
        merge_viewport_names(('A', 'B'), ('B', 'C'), minimum_overlap=2)


@pytest.mark.parametrize(
    'fixture',
    [
        'rebuild-top-04.png',
        'rebuild-top-03.png',
        'rebuild-bottom-scrollbar.png',
        '../material-live-single-ocr-final.png',
    ],
)
def test_unselected_real_fixtures_are_not_selected(fixture: str) -> None:
    from autowsgr.ui.material_inventory_scanner import has_selected_material

    assert not has_selected_material(_fixture(fixture))


def test_selected_material_badge_is_detected() -> None:
    from autowsgr.ui.material_inventory_scanner import has_selected_material

    screen = _material_screen(row_columns=(1,))
    screen[220:290, 145:215] = (20, 145, 235)

    assert has_selected_material(screen)


def test_material_scanner_has_no_portrait_or_feature_matching_path() -> None:
    source = Path(r'E:\AutoWSGR-backend\autowsgr\ui\material_inventory_scanner.py').read_text(
        encoding='utf-8'
    )

    for forbidden in ('ShipPortraitLibrary', 'ship_portrait_matcher', 'SIFT', 'SURF', 'ORB_create'):
        assert forbidden not in source


def test_adb_lossless_device_returns_rgb_and_forwards_shell() -> None:
    adb_device = MagicMock()
    adb_device.screenshot.return_value = MagicMock()
    adb_device.screenshot.return_value.convert.return_value = MagicMock()
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            'autowsgr.ui.material_inventory_scanner.np.asarray',
            lambda _image, dtype: rgb.astype(dtype),
        )
        device = AdbLosslessMaterialDevice('127.0.0.1:16416', adb_device=adb_device)

        assert np.array_equal(device.screenshot(), rgb)
        device.shell('input swipe 1580 200 1580 211 300')

    adb_device.screenshot.assert_called_once_with(error_ok=False)
    adb_device.shell.assert_called_once_with('input swipe 1580 200 1580 211 300')


def test_adb_lossless_device_click_uses_exact_shell_pixels() -> None:
    adb_device = MagicMock()
    adb_device.window_size.return_value = (1920, 1080)
    device = AdbLosslessMaterialDevice('127.0.0.1:16416', adb_device=adb_device)

    device.click(0.5, 0.25, delay=False)

    adb_device.shell.assert_called_once_with('input tap 960 270')


def test_complete_entry_navigates_then_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    device = MagicMock()
    ocr = MagicMock()
    navigation = MagicMock()
    scanner = MagicMock()
    expected = MagicMock()
    scanner.scan.return_value = expected
    monkeypatch.setattr(
        'autowsgr.ui.material_inventory_scanner.MaterialFirstIntensifyController',
        MagicMock(return_value=navigation),
    )
    monkeypatch.setattr(
        'autowsgr.ui.material_inventory_scanner.MaterialViewportReader',
        MagicMock(),
    )
    monkeypatch.setattr(
        'autowsgr.ui.material_inventory_scanner.AdbScrollbarStepper',
        MagicMock(),
    )
    monkeypatch.setattr(
        'autowsgr.ui.material_inventory_scanner.MaterialInventoryScanner',
        MagicMock(return_value=scanner),
    )

    result = scan_material_inventory_from_main(device, ocr, max_viewports=12)

    navigation.enter_material_selector_from_main.assert_called_once_with()
    scanner.scan.assert_called_once_with(max_viewports=12)
    assert result is expected
