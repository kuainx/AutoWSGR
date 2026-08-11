from __future__ import annotations

from dataclasses import replace

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
    TargetShipSnapshot,
    assign_target_occurrences,
    detect_complete_target_cards,
    merge_overlapping_target_pages,
)


def _snapshot(ship_id: int, visual_hash: int = 0, *, name: str = '舰') -> TargetShipSnapshot:
    return TargetShipSnapshot(
        ref=SelectionRef('pending'),
        ship_id=ship_id,
        name=name,
        ship_type=ShipType.DD,
        levels=ShipStats(),
        card=CardRect(10, 10, 110, 210),
        visual_hash=visual_hash,
        portrait_good_matches=20,
        portrait_match_ratio=0.2,
    )


def test_detects_complete_cards_and_excludes_clipped_card() -> None:
    screen = np.zeros((1000, 1600, 3), dtype=np.uint8)
    cyan = cv2.cvtColor(np.uint8([[[104, 230, 230]]]), cv2.COLOR_HSV2RGB)[0, 0].tolist()
    cv2.rectangle(screen, (80, 100), (239, 473), cyan, 4)
    cv2.rectangle(screen, (280, 100), (439, 473), cyan, 4)
    cv2.rectangle(screen, (80, 750), (239, 999), cyan, 4)
    boxes = detect_complete_target_cards(screen)
    assert len(boxes) == 2
    assert [box.left for box in boxes] == [78, 278]


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
    assert [item.ref.value for item in positioned] == ['target:7:0', 'target:7:1', 'target:8:0']
    assert [item.global_index for item in positioned] == [0, 1, 2]


class _Reader:
    def identify(self, _screen: np.ndarray, card: CardRect) -> TargetCardIdentity | None:
        if card.left > 250:
            return None
        return TargetCardIdentity(1, '舰', ShipType.DD, 1, 20, 0.2)

    def read_levels(
        self,
        _screen: np.ndarray,
        _card: CardRect,
        _identity: TargetCardIdentity,
    ) -> ShipStats | None:
        return ShipStats()


def test_viewport_fails_when_any_complete_card_is_unidentified() -> None:
    screen = np.zeros((1000, 1600, 3), dtype=np.uint8)
    cyan = cv2.cvtColor(np.uint8([[[104, 230, 230]]]), cv2.COLOR_HSV2RGB)[0, 0].tolist()
    cv2.rectangle(screen, (80, 100), (239, 473), cyan, 4)
    cv2.rectangle(screen, (280, 100), (439, 473), cyan, 4)
    scanner = TargetInventoryScanner(object(), _Reader(), settle_seconds=0)
    with pytest.raises(TargetInventoryScanError, match='未识别完整卡片'):
        scanner.read_viewport(screen, scan_step=0)
