from __future__ import annotations

import json
from typing import TYPE_CHECKING

from autowsgr.ui.intensify_workflow import ShipStats
from autowsgr.ui.target_strengthen_max import (
    TargetStrengthenMaxResolver,
    source_experience_per_level,
    source_to_canonical_ship_id,
)


if TYPE_CHECKING:
    from pathlib import Path


def test_source_id_mapping_and_refit_experience() -> None:
    assert source_to_canonical_ship_id(10057012) == 570
    assert source_to_canonical_ship_id(11008411) == 1084
    assert source_experience_per_level(10057012) == 20
    assert source_experience_per_level(11008411) == 12


def test_resolver_uses_ceiling_division(tmp_path: Path) -> None:
    source = [
        {
            'id': 10000113,
            'title': '舰',
            'strengthenSupply': {'atk': 0, 'torpedo': 0, 'def': 0, 'airDef': 0},
            'strengthenMax': {'atk': 625, 'torpedo': 0, 'def': 375, 'airDef': 750},
        }
    ]
    path = tmp_path / 'strengthen.json'
    path.write_text(json.dumps(source), encoding='utf-8')
    resolver = TargetStrengthenMaxResolver.from_source(path)
    assert resolver(1) == ShipStats(21, 0, 13, 25)
