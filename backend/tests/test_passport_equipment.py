import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.equipment import encode_equipment, equipment_items
from app.serializers import room_to_dict
from app.services.availability import equipment_categories


def test_composite_equipment_is_one_item():
    items = ['Радиомикрофоны: 3 ручных, 1 с оголовьем',
             'Конгресс-система: 12 проводных шт; 12 беспроводных шт.']
    assert equipment_items(encode_equipment(items)) == items
    assert equipment_categories(encode_equipment(items)) == {'микрофон', 'конгресс-система'}


@pytest.mark.parametrize('raw,expected', [('', []), (None, []), ('Проектор, компьютер', ['Проектор', 'компьютер'])])
def test_legacy_equipment(raw, expected):
    assert equipment_items(raw) == expected


def test_passport_payloads_are_consistent_and_serialized_losslessly():
    root = Path(__file__).resolve().parents[1] / 'app'
    manifest = json.loads((root / 'passport_equipment.json').read_text(encoding='utf-8'))
    catalog = json.loads((root / 'catalog_data.json').read_text(encoding='utf-8'))
    names = {b['code']: b['name'] for b in catalog['buildings']}
    by_key = {(names[r['building_code']], r['number']): r for r in catalog['rooms']}
    assert len(manifest['rooms']) == 99
    for entry in manifest['rooms']:
        room = by_key[(entry['building'], entry['number'])]
        assert room['equipment'] == entry['equipment']
        obj = SimpleNamespace(**{k: v for k, v in room.items() if k != 'equipment'}, id=1,
                              building_id=1, building=SimpleNamespace(name=entry['building'], image='', color='#ffffff'),
                              equipment=encode_equipment(entry['equipment']))
        assert room_to_dict(obj)['equipment'] == entry['equipment']
    room270 = by_key[('Второй учебный корпус', '270')]
    assert 'Конгресс-система: 12 шт.' in room270['equipment']
    assert not any('Потолочный' in item for item in room270['equipment'])
    baz = by_key[('Первый учебный корпус', 'БАЗ')]
    assert 'Семинар' not in baz['equipment']
