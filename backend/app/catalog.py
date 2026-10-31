import json
from pathlib import Path
from sqlalchemy import delete, func, select
from .database import SessionLocal
from .equipment import encode_equipment
from .models import Booking, BookingHistory, Building, Room

CATALOG_FILE = Path(__file__).with_name("catalog_data.json")

ROOM_FIELDS = ("name", "floor", "floor_display", "capacity", "area", "description", "usage_options",
               "images", "floor_plan", "color")


def sync_catalog(confirm: bool = False) -> dict:
    """Bring buildings and rooms in line with catalog_data.json without touching bookings.

    Rooms are matched by building name and number, so their ids, bookings and history
    stay. New rooms are added; rooms missing from the file are only listed (switching
    one off is an administrator's decision). Maximum capacity and the on/off state
    entered by hand are kept. Without `confirm` nothing is saved.
    """
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    stats = {"buildings_added": 0, "buildings_updated": 0, "rooms_added": 0, "rooms_updated": 0, "rooms_not_in_file": []}
    with SessionLocal() as db:
        buildings = {item.name: item for item in db.scalars(select(Building))}
        by_code = {}
        for item in data["buildings"]:
            building = buildings.get(item["name"])
            if building is None:
                building = Building(name=item["name"]); db.add(building); stats["buildings_added"] += 1
                buildings[item["name"]] = building
            elif (building.address, building.image, building.color) != (item["address"], item["image"], item["color"]):
                stats["buildings_updated"] += 1
            building.address, building.image, building.color = item["address"], item["image"], item["color"]
            by_code[item["code"]] = building
        db.flush()
        rooms = {(room.building_id, room.number): room for room in db.scalars(select(Room))}
        seen = set()
        for item in data["rooms"]:
            building = by_code[item["building_code"]]
            values = {field: item[field] for field in ROOM_FIELDS}
            values["equipment"] = encode_equipment(item["equipment"])
            room = rooms.get((building.id, item["number"]))
            if room is None:
                room = Room(number=item["number"], building=building, is_active=True, **values)
                if item.get("max_capacity"): room.max_capacity = item["max_capacity"]
                db.add(room); stats["rooms_added"] += 1
                continue
            seen.add(room.id)
            if any(getattr(room, field) != value for field, value in values.items()):
                stats["rooms_updated"] += 1
            for field, value in values.items():
                setattr(room, field, value)
            if room.max_capacity is not None and room.max_capacity < room.capacity:
                room.max_capacity = room.capacity
        stats["rooms_not_in_file"] = sorted(f"{room.building.name}: {room.number}" for room in rooms.values()
                                            if room.id not in seen and room.is_active)
        if confirm: db.commit()
        else: db.rollback()
    return stats


def count_bookings() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(Booking.id))) or 0


def replace_catalog() -> tuple[int, int]:
    """Wipe buildings, rooms AND all bookings, then load the catalog. Only for an empty
    or test database; a working service uses sync_catalog()."""
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        # The catalog file has no maximum capacity; keep what administrators entered by hand.
        kept_max = {(name, number): value for name, number, value in db.execute(
            select(Building.name, Room.number, Room.max_capacity).join(Room.building).where(Room.max_capacity.is_not(None)))}
        db.execute(delete(BookingHistory))
        db.execute(delete(Booking))
        db.execute(delete(Room))
        db.execute(delete(Building))
        db.flush()
        buildings = {}
        for item in data["buildings"]:
            building = Building(name=item["name"], address=item["address"], image=item["image"], color=item["color"])
            db.add(building); db.flush(); buildings[item["code"]] = building
        for item in data["rooms"]:
            building = buildings[item["building_code"]]
            db.add(Room(number=item["number"], name=item["name"], building=building,
                        floor=item["floor"], floor_display=item["floor_display"], capacity=item["capacity"],
                        max_capacity=item.get("max_capacity") or kept_max.get((building.name, item["number"])),
                        area=item["area"], equipment=encode_equipment(item["equipment"]),
                        description=item["description"], usage_options=item["usage_options"],
                        images=item["images"], floor_plan=item["floor_plan"], color=item["color"], is_active=True))
        db.commit()
    return len(data["buildings"]), len(data["rooms"])
