"""Candidate-constrained portrait matching for obscured ship cards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2

from autowsgr.types import ShipType
from autowsgr.vision.ship_card_recognizer import _SHIP_TYPE_CODES


if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True, slots=True)
class NamedPortraitRecord:
    ship_id: int
    name: str
    search_name: str
    ship_type: ShipType
    portrait_path: Path


@dataclass(frozen=True, slots=True)
class NamedPortraitMatch:
    record: NamedPortraitRecord
    good_matches: int
    template_keypoints: int

    @property
    def ratio(self) -> float:
        return 0.0 if self.template_keypoints == 0 else self.good_matches / self.template_keypoints


class NamedPortraitMatcher:
    """Match only forms already constrained by an independently OCRed ship name."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._records = self._load_records()
        self._sift = cv2.SIFT_create()
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._descriptor_cache: dict[Path, tuple[int, np.ndarray | None]] = {}

    def _load_records(self) -> tuple[NamedPortraitRecord, ...]:
        manifest = json.loads((self._root / 'manifest.json').read_text(encoding='utf-8'))
        records: list[NamedPortraitRecord] = []
        for entry in manifest.get('ships', []):
            portrait = entry.get('portrait')
            type_value = _SHIP_TYPE_CODES.get(str(entry.get('ship_type', '')).lower())
            if not portrait or type_value is None:
                continue
            records.append(
                NamedPortraitRecord(
                    ship_id=int(entry['id']),
                    name=str(entry['name']),
                    search_name=str(entry.get('search_name') or entry['name']),
                    ship_type=ShipType(type_value),
                    portrait_path=self._root / str(portrait),
                )
            )
        return tuple(records)

    @property
    def search_names(self) -> list[str]:
        """Return the authoritative name pool represented by this portrait set."""
        return list(dict.fromkeys(record.search_name for record in self._records))

    def _describe(self, image_rgb: np.ndarray) -> tuple[int, np.ndarray | None]:
        if image_rgb.ndim != 3 or image_rgb.shape[2] not in (3, 4):
            return (0, None)
        conversion = cv2.COLOR_RGBA2GRAY if image_rgb.shape[2] == 4 else cv2.COLOR_RGB2GRAY
        keypoints, descriptors = self._sift.detectAndCompute(
            cv2.cvtColor(image_rgb, conversion),
            None,
        )
        return len(keypoints), descriptors

    def _template_descriptors(self, record: NamedPortraitRecord) -> tuple[int, np.ndarray | None]:
        cached = self._descriptor_cache.get(record.portrait_path)
        if cached is not None:
            return cached
        image = cv2.imread(str(record.portrait_path), cv2.IMREAD_UNCHANGED)
        if image is None:
            result = (0, None)
        else:
            conversion = cv2.COLOR_BGRA2RGBA if image.shape[2] == 4 else cv2.COLOR_BGR2RGB
            result = self._describe(cv2.cvtColor(image, conversion))
        self._descriptor_cache[record.portrait_path] = result
        return result

    def identify(
        self,
        portrait_rgb: np.ndarray,
        name: str,
        *,
        min_good_matches: int = 12,
        min_ratio: float = 0.02,
        ambiguity_margin: int = 4,
    ) -> NamedPortraitMatch | None:
        _, query_descriptors = self._describe(portrait_rgb)
        if query_descriptors is None or len(query_descriptors) < 2:
            return None
        candidates = [
            record for record in self._records if name in (record.name, record.search_name)
        ]
        matches: list[NamedPortraitMatch] = []
        for record in candidates:
            keypoint_count, descriptors = self._template_descriptors(record)
            if descriptors is None or len(descriptors) < 2:
                continue
            pairs = self._matcher.knnMatch(descriptors, query_descriptors, k=2)
            good_matches = sum(
                1 for pair in pairs if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance
            )
            matches.append(NamedPortraitMatch(record, good_matches, keypoint_count))
        matches.sort(key=lambda item: (item.good_matches, item.ratio), reverse=True)
        if not matches:
            return None
        best = matches[0]
        if best.good_matches < min_good_matches or best.ratio < min_ratio:
            return None
        if len(matches) > 1 and best.good_matches - matches[1].good_matches < ambiguity_margin:
            return None
        return best
