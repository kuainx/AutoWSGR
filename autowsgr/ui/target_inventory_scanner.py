"""Fail-closed full inventory scanning for the intensify target selector."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

import cv2
import numpy as np

from autowsgr.ui.intensify_workflow import SelectionRef, ShipStats


if TYPE_CHECKING:
    from autowsgr.types import ShipType


class TargetInventoryScanError(RuntimeError):
    """Raised when the complete target inventory cannot be proven."""


@dataclass(frozen=True, slots=True)
class CardRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)


@dataclass(frozen=True, slots=True)
class TargetCardIdentity:
    ship_id: int
    name: str
    ship_type: ShipType
    visual_hash: int
    portrait_good_matches: int
    portrait_match_ratio: float


@dataclass(frozen=True, slots=True)
class TargetShipSnapshot:
    ref: SelectionRef
    ship_id: int
    name: str
    ship_type: ShipType
    levels: ShipStats
    card: CardRect
    visual_hash: int
    portrait_good_matches: int
    portrait_match_ratio: float
    scan_step: int = 0
    global_index: int = -1
    occurrence: int = -1


class TargetCardReader(Protocol):
    def identify(self, screen: np.ndarray, card: CardRect) -> TargetCardIdentity | None: ...

    def read_levels(
        self,
        screen: np.ndarray,
        card: CardRect,
        identity: TargetCardIdentity,
    ) -> ShipStats | None: ...


class TargetScanDevice(Protocol):
    def screenshot(self) -> np.ndarray: ...

    def rewind_target_list(self) -> None: ...

    def advance_target_list(self) -> None: ...


def visual_hash_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def merge_overlapping_target_pages(
    accumulated: list[TargetShipSnapshot],
    current: list[TargetShipSnapshot],
    *,
    max_hash_distance: int = 6,
) -> list[TargetShipSnapshot]:
    """Append only after finding one unique longest suffix/prefix alignment."""
    if not accumulated:
        return list(current)

    def same(left: TargetShipSnapshot, right: TargetShipSnapshot) -> bool:
        return left.ship_id == right.ship_id and visual_hash_distance(
            left.visual_hash, right.visual_hash
        ) <= max_hash_distance

    overlaps = [
        size
        for size in range(1, min(len(accumulated), len(current)) + 1)
        if all(
            same(left, right)
            for left, right in zip(accumulated[-size:], current[:size], strict=True)
        )
    ]
    if not overlaps:
        raise TargetInventoryScanError('目标舰列表滚动后无法建立可靠重叠')
    longest = max(overlaps)
    # A shorter valid suffix is expected whenever a longer one exists. Ambiguity
    # means the longest sequence itself occurs at more than one accumulated offset.
    signature = current[:longest]
    starts = [
        start
        for start in range(len(accumulated) - longest + 1)
        if all(
            same(left, right)
            for left, right in zip(
                accumulated[start : start + longest], signature, strict=True
            )
        )
    ]
    if starts != [len(accumulated) - longest]:
        raise TargetInventoryScanError(f'目标舰列表滚动重叠存在歧义: {starts}')
    return [*accumulated, *current[longest:]]


def assign_target_occurrences(
    cards: list[TargetShipSnapshot],
) -> list[TargetShipSnapshot]:
    occurrences: dict[int, int] = {}
    result: list[TargetShipSnapshot] = []
    for index, card in enumerate(cards):
        occurrence = occurrences.get(card.ship_id, 0)
        occurrences[card.ship_id] = occurrence + 1
        result.append(
            replace(
                card,
                ref=SelectionRef(f'target:{card.ship_id}:{occurrence}'),
                global_index=index,
                occurrence=occurrence,
            )
        )
    return result


def detect_complete_target_cards(screen: np.ndarray) -> tuple[CardRect, ...]:
    """Detect complete cyan-framed cards in row-major order."""
    height, width = screen.shape[:2]
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    cyan = cv2.inRange(
        hsv,
        np.array((96, 170, 120), dtype=np.uint8),
        np.array((112, 255, 255), dtype=np.uint8),
    )
    contours, _ = cv2.findContours(cyan, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    expected_width = width * 0.10
    expected_height = height * 0.374
    boxes: list[CardRect] = []
    for contour in contours:
        left, top, box_width, box_height = cv2.boundingRect(contour)
        if not (expected_width * 0.82 <= box_width <= expected_width * 1.18):
            continue
        if not (expected_height * 0.82 <= box_height <= expected_height * 1.18):
            continue
        right = left + box_width
        bottom = top + box_height
        if left <= 0 or top <= 0 or right >= width - 1 or bottom >= height * 0.94:
            continue
        boxes.append(CardRect(left, top, right, bottom))
    boxes.sort(key=lambda box: (round(box.top / max(1, height * 0.03)), box.left))
    return tuple(boxes)


class TargetInventoryScanner:
    def __init__(
        self,
        device: TargetScanDevice,
        reader: TargetCardReader,
        *,
        settle_seconds: float = 1.5,
    ) -> None:
        self._device = device
        self._reader = reader
        self._settle_seconds = settle_seconds

    def read_viewport(self, screen: np.ndarray, *, scan_step: int) -> list[TargetShipSnapshot]:
        cards = detect_complete_target_cards(screen)
        if not cards:
            raise TargetInventoryScanError('无法定位目标舰完整卡片')
        snapshots: list[TargetShipSnapshot] = []
        for card in cards:
            identity = self._reader.identify(screen, card)
            if identity is None:
                raise TargetInventoryScanError('目标舰页面存在未识别完整卡片，拒绝宣称扫描完成')
            levels = self._reader.read_levels(screen, card, identity)
            if levels is None:
                raise TargetInventoryScanError('目标舰页面存在未识别完整卡片，拒绝宣称扫描完成')
            snapshots.append(
                TargetShipSnapshot(
                    ref=SelectionRef('unassigned'),
                    ship_id=identity.ship_id,
                    name=identity.name,
                    ship_type=identity.ship_type,
                    levels=levels,
                    card=card,
                    visual_hash=identity.visual_hash,
                    portrait_good_matches=identity.portrait_good_matches,
                    portrait_match_ratio=identity.portrait_match_ratio,
                    scan_step=scan_step,
                )
            )
        return snapshots

    def scan_all(self, *, max_scrolls: int = 80) -> list[TargetShipSnapshot]:
        if max_scrolls < 1:
            raise ValueError('目标舰最大滚动次数必须大于 0')
        self._device.rewind_target_list()
        time.sleep(self._settle_seconds)
        accumulated = self.read_viewport(self._device.screenshot(), scan_step=0)
        stagnant = 0
        for scan_step in range(1, max_scrolls + 1):
            self._device.advance_target_list()
            time.sleep(self._settle_seconds)
            current = self.read_viewport(self._device.screenshot(), scan_step=scan_step)
            merged = merge_overlapping_target_pages(accumulated, current)
            if len(merged) == len(accumulated):
                stagnant += 1
                if stagnant >= 2:
                    return assign_target_occurrences(accumulated)
            else:
                accumulated = merged
                stagnant = 0
        raise TargetInventoryScanError(f'目标舰列表扫描超过最大滚动次数: {max_scrolls}')
