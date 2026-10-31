"""Import the Черняховского, 9 building passport into catalog assets and PostgreSQL."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MEDIA = ROOT / "frontend" / "public" / "catalog"
CATALOG_FILE = BACKEND / "app" / "catalog_data.json"
DEFAULT_PDF = Path.home() / "Downloads" / "Паспорт_УК_по_ул_Черняховского_д_9_стр_1_м_Аэропорт.pdf"

BUILDING = {
    "code": "airport",
    "name": "Учебный корпус на Черняховского",
    "address": "г. Москва, ул. Черняховского, д. 9, стр. 1",
    "image": "/catalog/buildings/airport.jpg",
    "color": "#6D4AA2",
}

# Rooms sharing a passport page intentionally share its photos and characteristics.
ROOM_GROUPS = [
    (3, ["104"], 1, 42, 58.7, ["Проектор", "Стационарный компьютер"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
    (4, ["107"], 1, 1, 28.1, ["Подогрев пищи"], ["Кейтеринг"], "Кафе 107"),
    (5, ["108"], 1, 1, 109.4, ["Проектор"], ["Обучение", "Проектная работа"], "Коворкинг 108"),
    (6, ["109"], 1, 40, 58.9, ["Проектор", "Стационарный компьютер"], ["Компьютерный класс", "Обучение", "Проектная работа"], "Компьютерный класс 109"),
    (8, ["205"], 2, 34, 60.3, ["Проектор", "Стационарный компьютер"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
    (9, ["207"], 2, 10, 29.5, ["Мобильный ТВ"], ["Переговорная"]),
    (11, ["302"], 3, 2, 20.5, ["Стационарный компьютер", "Настольный монитор"], ["Переговорная", "Преподавательская"]),
    (12, ["303"], 3, 2, 14.5, [], ["Переговорная", "Преподавательская"]),
    (13, ["305"], 3, 62, 91.9, ["Проектор", "Стационарный ноутбук"], ["Обучение", "Проектная работа"]),
    (15, ["403"], 4, 20, 31.0, ["Проектор"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
    (16, ["405"], 4, 90, 152.5, ["Мобильный ТВ"], ["Обучение", "Проектная работа", "Кейтеринг"]),
    (17, ["406"], 4, 2, 14.1, [], ["Переговорная", "Преподавательская"]),
    (18, ["407"], 4, 24, 31.2, ["Проектор", "Стационарный ноутбук"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
    (19, ["401А", "409А"], 4, 24, 34.6, ["Проектор", "Стационарный ноутбук"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
    (20, ["401Б", "401В", "409Г"], 4, 26, 35.2, ["Проектор", "Стационарный ноутбук"], ["Обучение", "Проектная работа", "Кейтеринг", "Штаб"]),
]
PLAN_PAGES = {1: 2, 2: 7, 3: 10, 4: 14}




def write_image(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image.data)


def build_entries(pdf_path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    building_photo = list(reader.pages[0].images)[0]
    write_image(building_photo, MEDIA / "buildings" / "airport.jpg")

    plans: dict[int, str] = {}
    for floor, page_number in PLAN_PAGES.items():
        images = list(reader.pages[page_number - 1].images)
        # Passport layout stores common backgrounds first, then the floor plan,
        # and finally the corridor photograph.
        plan = images[2]
        relative = f"plans/airport-floor-{floor}.jpg"
        write_image(plan, MEDIA / relative)
        plans[floor] = "/catalog/" + relative

    entries: list[dict] = []
    for group in ROOM_GROUPS:
        page_number, numbers, floor, capacity, area, equipment, usage, *custom_name = group
        page_images = list(reader.pages[page_number - 1].images)[2:4]
        photo_paths = []
        for index, image in enumerate(page_images, 1):
            relative = f"rooms/airport-page-{page_number}-{index}.jpg"
            write_image(image, MEDIA / relative)
            photo_paths.append("/catalog/" + relative)
        for number in numbers:
            name = custom_name[0] if custom_name else f"Аудитория {number}"
            description = f"Вместимость - {capacity} мест, площадь - {str(area).replace('.', ',')} кв. м."
            if number in {"107", "108"}:
                description = f"Вместимость уточняется по запросу, площадь - {str(area).replace('.', ',')} кв. м."
            entries.append({
                "building_code": BUILDING["code"], "number": number,
                "name": name if len(numbers) == 1 else f"Аудитория {number}",
                "floor": floor, "floor_display": f"{floor} этаж",
                "capacity": capacity, "area": area,
                "equipment": equipment, "usage_options": usage,
                "description": description, "images": photo_paths,
                "floor_plan": plans[floor], "color": BUILDING["color"],
            })
    return entries


def update_catalog(entries: list[dict]) -> None:
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    data["buildings"] = [item for item in data["buildings"] if item.get("code") != BUILDING["code"]]
    data["buildings"].append(BUILDING)
    data["rooms"] = [item for item in data["rooms"] if item.get("building_code") != BUILDING["code"]]
    data["rooms"].extend(entries)
    CATALOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_database(entries: list[dict]) -> None:
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Building, Room

    with SessionLocal() as db:
        building = db.scalar(select(Building).where(Building.name == BUILDING["name"]))
        if not building:
            building = Building(name=BUILDING["name"])
            db.add(building)
            db.flush()
        building.address, building.image, building.color = BUILDING["address"], BUILDING["image"], BUILDING["color"]
        for item in entries:
            room = db.scalar(select(Room).where(Room.building_id == building.id, Room.number == item["number"]))
            if not room:
                room = Room(building_id=building.id, number=item["number"])
                db.add(room)
            room.name = item["name"]
            room.floor, room.floor_display = item["floor"], item["floor_display"]
            room.capacity, room.area = item["capacity"], item["area"]
            room.equipment = ", ".join(item["equipment"])
            room.description, room.usage_options = item["description"], item["usage_options"]
            room.images, room.floor_plan = item["images"], item["floor_plan"]
            room.color, room.is_active = item["color"], True
        db.commit()


def main() -> None:
    database_only = "--database-only" in sys.argv
    assets_only = "--assets-only" in sys.argv
    arguments = [value for value in sys.argv[1:] if not value.startswith("--")]
    pdf_path = Path(arguments[0]) if arguments else DEFAULT_PDF
    if database_only:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        entries = [item for item in data["rooms"] if item.get("building_code") == BUILDING["code"]]
        if not entries:
            raise SystemExit("Airport catalog entries have not been prepared")
        upsert_database(entries)
        print(f"Imported {BUILDING['name']} into PostgreSQL: {len(entries)} rooms")
        return
    if not pdf_path.is_file():
        raise SystemExit(f"Passport not found: {pdf_path}")
    entries = build_entries(pdf_path)
    update_catalog(entries)
    if not assets_only:
        upsert_database(entries)
    print(f"Prepared {BUILDING['name']}: {len(entries)} rooms")


if __name__ == "__main__":
    main()
