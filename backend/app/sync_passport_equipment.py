"""Update only verified room equipment, without replacing catalog or bookings.

Preview: python -m app.sync_passport_equipment
Apply: python -m app.sync_passport_equipment --apply --backup-dir PATH
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from sqlalchemy import text
from .database import engine
from .equipment import encode_equipment, equipment_items

MANIFEST = Path(__file__).with_name('passport_equipment.json')


def synchronize(apply: bool = False, backup_dir: Path | None = None) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    expected = {(item['building'], item['number']): item for item in manifest['rooms']}
    if len(expected) != 99 or len(expected) != len(manifest['rooms']):
        raise RuntimeError('Expected 99 uniquely identified passport rooms')
    if apply and backup_dir is None:
        raise ValueError('A backup directory is required for --apply')
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text("SET LOCAL statement_timeout = '30s'"))
        # Lock the verified buildings' room rows, never booking records.
        names = sorted({key[0] for key in expected})
        rows = conn.execute(text('''SELECT r.id, r.number, r.equipment, b.name AS building
            FROM rooms r JOIN buildings b ON b.id = r.building_id
            WHERE b.name = ANY(:names) ORDER BY r.id FOR UPDATE OF r'''), {'names': names}).mappings().all()
        actual = {(row['building'], row['number']): row for row in rows}
        missing = sorted(set(expected) - set(actual))
        if missing:
            raise RuntimeError(f'No changes applied; missing rooms: {missing}')
        updates = []
        for key, item in expected.items():
            row = actual[key]
            encoded = encode_equipment(item['equipment'])
            if row['equipment'] != encoded:
                updates.append({'id': row['id'], 'building': row['building'], 'number': row['number'],
                                'before': row['equipment'], 'after': encoded})
        result = {'matched': len(expected), 'changed': len(updates), 'applied': False}
        if not apply or not updates:
            return result
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = backup_dir / f'room-equipment-before-{stamp}.json'
        with backup.open('x', encoding='utf-8') as stream:
            json.dump({'created_at': stamp, 'field': 'rooms.equipment', 'updates': updates}, stream,
                      ensure_ascii=False, indent=2)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        conn.execute(text('UPDATE rooms SET equipment = :after WHERE id = :id'), updates)
        for key, item in expected.items():
            current = conn.execute(text('SELECT equipment FROM rooms WHERE id = :id'),
                                   {'id': actual[key]['id']}).scalar_one()
            if equipment_items(current) != item['equipment']:
                raise RuntimeError(f'Verification failed for {key}; transaction rolled back')
        result.update(applied=True, backup=str(backup))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(synchronize(args.apply, args.backup_dir), ensure_ascii=False))
