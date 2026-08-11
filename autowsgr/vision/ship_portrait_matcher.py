from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from numpy.typing import NDArray

from autowsgr.types import ShipType


if TYPE_CHECKING:
    from collections.abc import Iterable


_TYPE_CODES: dict[str, ShipType] = {
    'cv': ShipType.CV,
    'cvl': ShipType.CVL,
    'av': ShipType.AV,
    'bb': ShipType.BB,
    'bbv': ShipType.BBV,
    'bc': ShipType.BC,
    'ca': ShipType.CA,
    'cav': ShipType.CAV,
    'clt': ShipType.CLT,
    'cl': ShipType.CL,
    'bm': ShipType.BM,
    'dd': ShipType.DD,
    'ssg': ShipType.SSG,
    'ss': ShipType.SS,
    'sc': ShipType.SC,
    'ap': ShipType.NAP,
    'nap': ShipType.NAP,
    'asdg': ShipType.ASDG,
    'ddg': ShipType.ASDG,
    'aadg': ShipType.AADG,
    'ddgaa': ShipType.AADG,
    'kp': ShipType.KP,
    'cg': ShipType.CG,
    'cgaa': ShipType.CG,
    'bg': ShipType.CBG,
    'cbg': ShipType.CBG,
    'bbg': ShipType.BG,
}


@dataclass(frozen=True, slots=True)
class ShipPortraitRecord:
    ship_id: int
    name: str
    search_name: str
    variant: str
    ship_type: ShipType
    country: str
    portrait_path: Path


@dataclass(frozen=True, slots=True)
class ShipPortraitMatch:
    record: ShipPortraitRecord
    good_matches: int
    template_keypoints: int

    @property
    def ratio(self) -> float:
        if self.template_keypoints == 0:
            return 0.0
        return self.good_matches / self.template_keypoints


DescriptorSet = tuple[int, NDArray[np.float32] | None]


class ShipPortraitLibrary:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records = self._load_records()
        self._sift = cv2.SIFT_create()
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._descriptor_cache: dict[Path, DescriptorSet] = {}
        self._portrait_descriptor_cache: dict[bytes, DescriptorSet] = {}

    def _load_records(self) -> tuple[ShipPortraitRecord, ...]:
        manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        records: list[ShipPortraitRecord] = []
        for entry in manifest.get('ships', []):
            portrait = entry.get('portrait')
            if not portrait:
                continue
            type_code = str(entry.get('ship_type', '')).lower()
            records.append(
                ShipPortraitRecord(
                    ship_id=int(entry['id']),
                    name=str(entry['name']),
                    search_name=str(entry.get('search_name') or entry['name']),
                    variant=str(entry.get('variant') or 'normal'),
                    ship_type=_TYPE_CODES.get(type_code, ShipType.Other),
                    country=str(entry.get('country') or 'other'),
                    portrait_path=self.root / str(portrait),
                )
            )
        return tuple(records)

    def records_for_search_name(self, name: str) -> tuple[ShipPortraitRecord, ...]:
        """Return every canonical form rendered with the exact search name."""
        return tuple(record for record in self.records if record.search_name == name)

    @staticmethod
    def _gray(image_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
        if image_rgb.ndim == 2:
            return image_rgb
        if image_rgb.ndim != 3 or image_rgb.shape[2] not in (3, 4):
            raise ValueError('portrait_rgb must be a grayscale, RGB, or RGBA image')
        conversion = cv2.COLOR_RGBA2GRAY if image_rgb.shape[2] == 4 else cv2.COLOR_RGB2GRAY
        return cv2.cvtColor(image_rgb, conversion)

    def _describe(self, image_rgb: NDArray[np.uint8]) -> DescriptorSet:
        keypoints, descriptors = self._sift.detectAndCompute(self._gray(image_rgb), None)
        return len(keypoints), descriptors

    def _template_descriptors(self, record: ShipPortraitRecord) -> DescriptorSet:
        cached = self._descriptor_cache.get(record.portrait_path)
        if cached is not None:
            return cached
        image_bgr = cv2.imread(str(record.portrait_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            result: DescriptorSet = (0, None)
        else:
            result = self._describe(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        self._descriptor_cache[record.portrait_path] = result
        return result

    def _portrait_descriptors(self, portrait_rgb: NDArray[np.uint8]) -> DescriptorSet:
        contiguous = np.ascontiguousarray(portrait_rgb)
        digest = hashlib.blake2b(digest_size=16)
        digest.update(str(contiguous.shape).encode())
        digest.update(contiguous.dtype.str.encode())
        digest.update(contiguous.data)
        key = digest.digest()
        cached = self._portrait_descriptor_cache.get(key)
        if cached is None:
            cached = self._describe(contiguous)
            self._portrait_descriptor_cache[key] = cached
        return cached

    def identify(
        self,
        portrait_rgb: NDArray[np.uint8],
        *,
        allowed_types: Iterable[ShipType] | None = None,
        candidate_names: Iterable[str] | None = None,
        min_good_matches: int = 12,
        min_ratio: float = 0.04,
        ambiguity_margin: int = 4,
    ) -> ShipPortraitMatch | None:
        _, portrait_descriptors = self._portrait_descriptors(portrait_rgb)
        if portrait_descriptors is None or len(portrait_descriptors) < 2:
            return None

        allowed_type_set = set(allowed_types) if allowed_types is not None else None
        candidate_name_set = set(candidate_names) if candidate_names is not None else None
        matches: list[ShipPortraitMatch] = []
        for record in self.records:
            if allowed_type_set is not None and record.ship_type not in allowed_type_set:
                continue
            if candidate_name_set is not None and not (
                record.name in candidate_name_set or record.search_name in candidate_name_set
            ):
                continue
            template_keypoints, template_descriptors = self._template_descriptors(record)
            if template_descriptors is None or len(template_descriptors) == 0:
                continue
            pairs = self._matcher.knnMatch(template_descriptors, portrait_descriptors, k=2)
            good_matches = sum(
                1 for pair in pairs if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance
            )
            matches.append(ShipPortraitMatch(record, good_matches, template_keypoints))

        if not matches:
            return None
        matches.sort(key=lambda match: (match.good_matches, match.ratio), reverse=True)
        best = matches[0]
        if best.good_matches < min_good_matches or best.ratio < min_ratio:
            return None
        if len(matches) > 1 and best.good_matches - matches[1].good_matches < ambiguity_margin:
            return None
        return best
