"""Lossless equipment lists in the existing TEXT column, with legacy support."""
import json


def equipment_items(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        decoded = None
    if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
        return [item.strip() for item in decoded if item.strip()]
    # Existing catalog entries not yet converted retain their previous behavior.
    return [item.strip() for item in value.split(',') if item.strip()]


def encode_equipment(items: list[str]) -> str:
    if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError('Equipment must be a list of non-empty strings')
    return json.dumps([item.strip() for item in items], ensure_ascii=False)
