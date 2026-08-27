from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from autowsgr.types import ShipType
from autowsgr.ui.intensify_workflow import SelectionRef, ShipStats
from autowsgr.ui.target_inventory_scanner import (
    CardRect,
    TargetCardIdentity,
    TargetInventoryScanError,
    TargetInventoryScanner,
    TargetInventorySnapshot,
    TargetShipSnapshot,
    assign_target_occurrences,
    detect_complete_target_cards,
    merge_overlapping_target_pages,
    target_viewport_rows,
)


def _snapshot(
    ship_id: int,
    visual_hash: int = 0,
    *,
    name: str = '舰',
    row: int = 0,
    column: int = 0,
) -> TargetShipSnapshot:
    top = 10 + row * 220
    left = 10 + column * 120
    return TargetShipSnapshot(
        ref=SelectionRef('pending'),
        ship_id=ship_id,
        name=name,
        ship_type=ShipType.DD,
        levels=ShipStats(),
        card=CardRect(left, top, left + 100, top + 200),
        visual_hash=visual_hash,
        identity_confidence=0.9,
        identity_match_key='gallery/ship.png',
    )


def _rows(*rows: tuple[int, ...]) -> list[TargetShipSnapshot]:
    return [
        _snapshot(ship_id, ship_id, row=row_index, column=column)
        for row_index, row in enumerate(rows)
        for column, ship_id in enumerate(row)
    ]


def test_detects_complete_cards_and_excludes_clipped_card() -> None:
    screen = np.zeros((1000, 1600, 3), dtype=np.uint8)
    cyan = cv2.cvtColor(np.uint8([[[104, 230, 230]]]), cv2.COLOR_HSV2RGB)[0, 0].tolist()
    cv2.rectangle(screen, (80, 100), (239, 473), cyan, 4)
    cv2.rectangle(screen, (280, 100), (439, 473), cyan, 4)
    cv2.rectangle(screen, (80, 750), (239, 999), cyan, 4)
    boxes = detect_complete_target_cards(screen)
    assert len(boxes) == 2
    assert [box.left for box in boxes] == [78, 278]


def test_excludes_slightly_clipped_1080p_card() -> None:
    screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cyan = cv2.cvtColor(np.uint8([[[104, 230, 230]]]), cv2.COLOR_HSV2RGB)[0, 0].tolist()
    cv2.rectangle(screen, (86, 190), (277, 594), cyan, 1)
    cv2.rectangle(screen, (931, 622), (1122, 1010), cyan, 1)

    boxes = detect_complete_target_cards(screen)

    assert boxes == (CardRect(86, 190, 278, 595),)


def test_merge_uses_identity_and_portrait_not_levels() -> None:
    old = [_snapshot(1, 1), _snapshot(2, 2)]
    changed = [_snapshot(2, 2), _snapshot(3, 3)]
    changed[0] = replace(changed[0], levels=ShipStats(firepower=9))
    assert [item.ship_id for item in merge_overlapping_target_pages(old, changed)] == [1, 2, 3]


def test_merge_rejects_missing_or_ambiguous_overlap() -> None:
    with pytest.raises(TargetInventoryScanError, match='无法建立'):
        merge_overlapping_target_pages([_snapshot(1)], [_snapshot(2)])
    with pytest.raises(TargetInventoryScanError, match='歧义'):
        merge_overlapping_target_pages(
            [_snapshot(1), _snapshot(2), _snapshot(1), _snapshot(2)],
            [_snapshot(1), _snapshot(2)],
        )


def test_occurrences_preserve_duplicate_targets() -> None:
    positioned = assign_target_occurrences([_snapshot(7), _snapshot(7), _snapshot(8)])
    assert all(item.ref.value.startswith('target:') for item in positioned)
    assert all(len(item.ref.value.split(':')) == 7 for item in positioned)
    assert len({item.ref.value for item in positioned}) == 3
    assert [item.global_index for item in positioned] == [0, 1, 2]


def test_target_inventory_snapshot_is_complete_immutable_and_revision_bound() -> None:
    positioned = tuple(assign_target_occurrences([_snapshot(7), _snapshot(7), _snapshot(8)]))
    revision = positioned[0].ref.value.split(':')[1]

    snapshot = TargetInventorySnapshot(
        targets=positioned,
        total=3,
        complete=True,
        revision=revision,
    )

    assert snapshot.targets is positioned
    assert [item.occurrence for item in snapshot.targets] == [0, 1, 0]
    with pytest.raises(FrozenInstanceError):
        snapshot.total = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    ('targets', 'total', 'complete', 'revision', 'message'),
    [
        ((), 0, False, 'revision', '完整'),
        ((), 1, True, 'revision', '不能为空'),
        ((), 0, True, '', 'revision'),
    ],
)
def test_target_inventory_snapshot_rejects_invalid_aggregate(
    targets: tuple[TargetShipSnapshot, ...],
    total: int,
    complete: bool,
    revision: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TargetInventorySnapshot(targets, total, complete, revision)


def test_target_inventory_snapshot_rejects_mixed_or_duplicate_refs() -> None:
    positioned = tuple(assign_target_occurrences([_snapshot(7), _snapshot(8)]))
    revision = positioned[0].ref.value.split(':')[1]
    mixed = replace(
        positioned[1], ref=SelectionRef(positioned[1].ref.value.replace(revision, 'other'))
    )

    with pytest.raises(ValueError, match='多个 revision'):
        TargetInventorySnapshot((positioned[0], mixed), 2, True, revision)
    duplicate_ref = replace(positioned[1], ref=positioned[0].ref)
    with pytest.raises(ValueError, match='引用必须唯一'):
        TargetInventorySnapshot((positioned[0], duplicate_ref), 2, True, revision)


class _Reader:
    def identify_all(
        self,
        _screen: np.ndarray,
        cards: tuple[CardRect, ...],
    ) -> tuple[TargetCardIdentity, ...]:
        return tuple(
            TargetCardIdentity(1, '舰', ShipType.DD, 1, 0.9, 'gallery/ship.png')
            for card in cards
            if card.left <= 250
        )

    def read_levels(
        self,
        _screen: np.ndarray,
        _card: CardRect,
        _identity: TargetCardIdentity,
    ) -> ShipStats | None:
        return ShipStats()


class _ScanDevice:
    def __init__(self, screens: list[np.ndarray], *, at_bottom: bool) -> None:
        self._screens = iter(screens)
        self._at_bottom = at_bottom

    def screenshot(self) -> np.ndarray:
        return next(self._screens)

    def rewind_target_list(self) -> None:
        pass

    def advance_target_list(self) -> np.ndarray:
        return next(self._screens)

    def target_list_at_bottom(self, _screen: np.ndarray) -> bool:
        return self._at_bottom


def test_viewport_fails_when_any_complete_card_is_unidentified() -> None:
    screen = np.zeros((1000, 1600, 3), dtype=np.uint8)
    cyan = cv2.cvtColor(np.uint8([[[104, 230, 230]]]), cv2.COLOR_HSV2RGB)[0, 0].tolist()
    cv2.rectangle(screen, (80, 100), (239, 473), cyan, 4)
    cv2.rectangle(screen, (280, 100), (439, 473), cyan, 4)
    scanner = TargetInventoryScanner(object(), _Reader(), settle_seconds=0)
    with pytest.raises(TargetInventoryScanError, match='未识别完整卡片'):
        scanner.read_viewport(screen, scan_step=0)


def test_viewport_rows_preserve_short_final_row() -> None:
    viewport = _rows((1, 2, 3), (4, 5))

    assert [[item.ship_id for item in row] for row in target_viewport_rows(viewport)] == [
        [1, 2, 3],
        [4, 5],
    ]


def test_advance_accepts_previous_lower_row_with_new_complete_content() -> None:
    previous = _rows(tuple(range(1, 8)), tuple(range(8, 15)))
    current = _rows(tuple(range(8, 15)), tuple(range(15, 22)))
    screen = np.zeros((1, 1, 3), dtype=np.uint8)
    device = MagicMock()
    device.advance_target_list.return_value = screen
    device.target_list_at_bottom.return_value = False
    scanner = TargetInventoryScanner(device, _Reader(), settle_seconds=0)
    scanner.read_viewport = MagicMock(return_value=current)

    result, result_screen = scanner.advance_overlapping_viewport(previous, scan_step=1)

    assert result is current
    assert result_screen is screen
    device.advance_target_list.assert_called_once_with()


def test_advance_rejects_wholly_new_two_row_viewport() -> None:
    previous = _rows(tuple(range(1, 8)), tuple(range(8, 15)))
    current = _rows(tuple(range(15, 22)), tuple(range(22, 29)))
    device = MagicMock()
    device.advance_target_list.return_value = np.zeros((1, 1, 3), dtype=np.uint8)
    scanner = TargetInventoryScanner(device, _Reader(), settle_seconds=0)
    scanner.read_viewport = MagicMock(return_value=current)

    with pytest.raises(TargetInventoryScanError, match='丢失完整锚点行'):
        scanner.advance_overlapping_viewport(previous, scan_step=1)

    device.advance_target_list.assert_called_once_with()


def test_intermediate_clipped_observation_does_not_consume_logical_scan_step() -> None:
    previous = _rows(tuple(range(1, 8)), tuple(range(8, 15)))
    clipped = _rows(tuple(range(8, 15)))
    clipped = [replace(item, card=replace(item.card, top=120, bottom=320)) for item in clipped]
    current = _rows(tuple(range(8, 15)), tuple(range(15, 22)))
    screens = [
        np.zeros((1, 1, 3), dtype=np.uint8),
        np.ones((1, 1, 3), dtype=np.uint8),
    ]
    device = MagicMock()
    device.advance_target_list.side_effect = screens
    device.target_list_at_bottom.return_value = False
    scanner = TargetInventoryScanner(device, _Reader(), settle_seconds=0)
    scanner.read_viewport = MagicMock(side_effect=(clipped, current))

    result, _screen = scanner.advance_overlapping_viewport(previous, scan_step=1)

    assert result is current
    assert device.advance_target_list.call_count == 2
    assert {item.scan_step for item in result} == {0}
    assert scanner.read_viewport.call_args_list[0].kwargs['scan_step'] == 1
    assert scanner.read_viewport.call_args_list[1].kwargs['scan_step'] == 1


def test_advance_rejects_unchanged_non_bottom_viewport() -> None:
    previous = _rows(tuple(range(1, 8)), tuple(range(8, 15)))
    device = MagicMock()
    device.advance_target_list.return_value = np.zeros((1, 1, 3), dtype=np.uint8)
    scanner = TargetInventoryScanner(device, _Reader(), settle_seconds=0)
    scanner.read_viewport = MagicMock(return_value=previous)

    with pytest.raises(TargetInventoryScanError, match='没有产生可观测进度'):
        scanner.advance_overlapping_viewport(previous, scan_step=1)

    device.advance_target_list.assert_called_once_with()


def test_navigate_to_viewport_reuses_identity_gated_logical_steps() -> None:
    initial = _rows(tuple(range(1, 8)), tuple(range(8, 15)))
    next_viewport = _rows(tuple(range(8, 15)), tuple(range(15, 22)))
    device = MagicMock()
    device.screenshot.return_value = np.zeros((1, 1, 3), dtype=np.uint8)
    scanner = TargetInventoryScanner(device, _Reader(), settle_seconds=0)
    scanner.read_viewport = MagicMock(return_value=initial)
    scanner.advance_overlapping_viewport = MagicMock(return_value=(next_viewport, object()))

    result = scanner.navigate_to_viewport(1)

    assert result is next_viewport
    scanner.advance_overlapping_viewport.assert_called_once_with(initial, scan_step=1)


def test_scan_snapshot_wraps_only_a_completed_scan() -> None:
    scanner = TargetInventoryScanner(object(), _Reader(), settle_seconds=0)
    scanner.scan_all = MagicMock(
        return_value=assign_target_occurrences([_snapshot(7), _snapshot(8)])
    )

    snapshot = scanner.scan_snapshot(max_scrolls=3)

    assert isinstance(snapshot, TargetInventorySnapshot)
    assert snapshot.complete is True
    assert snapshot.total == 2
    assert isinstance(snapshot.targets, tuple)
    assert snapshot.revision == snapshot.targets[0].ref.value.split(':')[1]
    scanner.scan_all.assert_called_once_with(max_scrolls=3)
