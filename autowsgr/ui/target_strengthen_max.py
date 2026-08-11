"""Target-only strengthening MAX resolver derived from the source data snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from autowsgr.ui.intensify_workflow import ShipStats


if TYPE_CHECKING:
    from pathlib import Path


_BASE_EXPERIENCE = {11: 10, 12: 20, 13: 30}


def source_to_canonical_ship_id(source_id: int) -> int:
    prefix = source_id // 1_000_000
    if prefix not in (10, 11):
        raise ValueError(f'未知强化数据形态前缀: {source_id}')
    return (prefix - 10) * 1000 + (source_id // 100) % 10_000


def source_experience_per_level(source_id: int) -> int:
    try:
        value = _BASE_EXPERIENCE[source_id % 100]
    except KeyError as error:
        raise ValueError(f'未知强化经验类别: {source_id}') from error
    return value * 6 // 5 if source_id // 1_000_000 == 11 else value


@dataclass(frozen=True, slots=True)
class TargetStrengthenMaxResolver:
    levels_by_ship_id: dict[int, ShipStats]

    @classmethod
    def from_source(cls, path: Path) -> TargetStrengthenMaxResolver:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, list):
            raise TypeError('强化数据根节点必须是数组')
        result: dict[int, ShipStats] = {}
        for item in payload:
            if not isinstance(item, dict) or set(item) != {
                'id',
                'title',
                'strengthenSupply',
                'strengthenMax',
            }:
                raise ValueError('强化数据记录 schema 不匹配')
            source_id = int(item['id'])
            maximum = item['strengthenMax']
            if not isinstance(maximum, dict) or set(maximum) != {
                'atk',
                'torpedo',
                'def',
                'airDef',
            }:
                raise ValueError(f'强化上限 schema 不匹配: {source_id}')
            divisor = source_experience_per_level(source_id)
            raw_values = [int(maximum[field]) for field in ('atk', 'torpedo', 'def', 'airDef')]
            if any(value < 0 for value in raw_values):
                raise ValueError(f'强化上限不能为负数: {source_id}')
            displayed = [(value + divisor - 1) // divisor for value in raw_values]

            ship_id = source_to_canonical_ship_id(source_id)
            if ship_id in result:
                raise ValueError(f'规范舰船 ID 重复: {ship_id}')
            result[ship_id] = ShipStats(
                firepower=displayed[0],
                torpedo=displayed[1],
                armor=displayed[2],
                anti_air=displayed[3],
            )
        return cls(result)

    def __call__(self, ship_id: int) -> ShipStats | None:
        return self.levels_by_ship_id.get(ship_id)
