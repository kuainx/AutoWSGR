from __future__ import annotations

import json
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest

from autowsgr.types import ShipType
from autowsgr.vision.ship_portrait_matcher import ShipPortraitLibrary


if TYPE_CHECKING:
    from pathlib import Path


def _portrait(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = np.full((128, 128, 3), 235, dtype=np.uint8)
    for _ in range(18):
        center = tuple(int(value) for value in rng.integers(8, 120, size=2))
        radius = int(rng.integers(3, 14))
        color = tuple(int(value) for value in rng.integers(0, 210, size=3))
        cv2.circle(image, center, radius, color, -1)
    cv2.putText(image, str(seed), (12, 112), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (10, 10, 10), 3)
    return image


def _library(tmp_path: Path, portraits: list[tuple[dict[str, object], np.ndarray]]) -> ShipPortraitLibrary:
    assets = tmp_path / 'assets'
    assets.mkdir()
    ships = []
    for entry, image_rgb in portraits:
        portrait_path = assets / f"{entry['id']}.png"
        cv2.imwrite(str(portrait_path), cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
        ships.append({**entry, 'portrait': f"assets/{entry['id']}.png"})
    (tmp_path / 'manifest.json').write_text(json.dumps({'ships': ships}), encoding='utf-8')
    return ShipPortraitLibrary(tmp_path)


def _entry(
    ship_id: int,
    name: str,
    ship_type: str,
    *,
    search_name: str | None = None,
) -> dict[str, object]:
    return {
        'id': ship_id,
        'name': name,
        'search_name': search_name or name,
        'variant': 'normal',
        'ship_type': ship_type,
        'country': 'china',
    }


def test_identify_returns_canonical_record_and_match_evidence(tmp_path: Path) -> None:
    target = _portrait(10)
    library = _library(
        tmp_path,
        [
            (_entry(1, 'Alpha', 'dd', search_name='Alpha Search'), target),
            (_entry(2, 'Beta', 'bb'), _portrait(20)),
        ],
    )

    match = library.identify(target)

    assert match is not None
    assert match.record.ship_id == 1
    assert match.record.name == 'Alpha'
    assert match.record.search_name == 'Alpha Search'
    assert match.record.variant == 'normal'
    assert match.record.ship_type is ShipType.DD
    assert match.record.country == 'china'
    assert match.good_matches >= 12
    assert match.template_keypoints > 0
    assert match.ratio == pytest.approx(match.good_matches / match.template_keypoints)


def test_identify_filters_by_type_and_canonical_or_search_name(tmp_path: Path) -> None:
    target = _portrait(30)
    library = _library(
        tmp_path,
        [
            (_entry(1, 'Alpha', 'asdg', search_name='Alpha Search'), target),
            (_entry(2, 'Beta', 'bb'), _portrait(40)),
        ],
    )

    assert library.identify(target, allowed_types={ShipType.BB}) is None
    assert library.identify(target, candidate_names={'Beta'}) is None
    by_name = library.identify(target, candidate_names={'Alpha Search'})
    assert by_name is not None
    assert by_name.record.ship_type is ShipType.ASDG


@pytest.mark.parametrize(
    ('code', 'expected'),
    [
        ('asdg', ShipType.ASDG),
        ('aadg', ShipType.AADG),
        ('kp', ShipType.KP),
        ('bg', ShipType.CBG),
        ('bbg', ShipType.BG),
        ('future_type', ShipType.Other),
    ],
)
def test_manifest_type_codes_are_safe(tmp_path: Path, code: str, expected: ShipType) -> None:
    library = _library(tmp_path, [(_entry(1, 'Alpha', code), _portrait(50))])

    assert library.records[0].ship_type is expected


def test_identify_rejects_weak_and_ambiguous_matches(tmp_path: Path) -> None:
    target = _portrait(60)
    library = _library(
        tmp_path,
        [
            (_entry(1, 'Alpha', 'dd'), target),
            (_entry(2, 'Alpha Copy', 'dd'), target.copy()),
        ],
    )

    assert library.identify(np.full_like(target, 127)) is None
    assert library.identify(target) is None
    accepted = library.identify(target, candidate_names={'Alpha'})
    assert accepted is not None
    assert accepted.record.ship_id == 1


def test_descriptor_cache_reuses_query_and_template_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _portrait(70)
    library = _library(tmp_path, [(_entry(1, 'Alpha', 'dd'), target)])
    calls = 0
    original = library._describe

    def counted(image_rgb: np.ndarray) -> tuple[int, np.ndarray | None]:
        nonlocal calls
        calls += 1
        return original(image_rgb)

    monkeypatch.setattr(library, '_describe', counted)

    assert library.identify(target) is not None
    assert library.identify(target.copy()) is not None
    assert calls == 2
