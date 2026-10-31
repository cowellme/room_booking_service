"""Build the normalized room catalog and its media from the supplied passports."""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import sys
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "room-booking-calendar"
PDF_DIR = ROOT / "tmp" / "pdfs"
MEDIA = ROOT / "frontend" / "public" / "catalog"
OUTPUT = ROOT / "backend" / "app" / "catalog_data.json"

SOURCES = [
    dict(code="b1", name="Первый учебный корпус", address="проспект Вернадского, 82, корпус 1", json="1_1.pdf.json", pdf="building-1.pdf", pages=list(range(5,12))+list(range(13,17))+list(range(18,23))+[24]+list(range(26,34))+list(range(35,41))+list(range(42,46)), plans={"1 этаж":4,"Антресоль":12,"2 этаж":17,"3 этаж":25,"8 этаж":34,"9 этаж":41}, image="1_bilding.png"),
    dict(code="b2", name="Второй учебный корпус", address="проспект Вернадского, 82, корпус 2", json="2_2pdf.json", pdf="building-2.pdf", pages=[5,6,8,9,11,12,15,16,17,13,19,20,21,22,23,24,25], plans={"1 этаж":4,"2 этаж":7,"1 этаж (пристройка)":10,"2 этаж (пристройка)":14,"3 этаж (пристройка)":18}, image="2_bilding.png"),
    dict(code="b5", name="Пятый учебный корпус", address="проспект Вернадского, 82, корпус 5", json="5_корпус.json", pdf="building-5.pdf", pages=list(range(5,8))+list(range(9,12))+list(range(13,17))+list(range(18,21))+list(range(22,40)), plans={"1 этаж":4,"2 этаж":8,"3 этаж":12,"4 этаж":17,"5 этаж":21}, image="5_bilding.png"),
    dict(code="p1", name="Корпус на Пречистенской набережной № 1", address="Пречистенская набережная, корпус 1", json="1_пречистенка.json", pdf="building-prech.pdf", pages=[3,4,5,6,7,8,10,11,12], plans={}, image="1_pre_bilding.png"),
    dict(code="p2", name="Корпус на Пречистенской набережной № 2", address="Пречистенская набережная, корпус 2", json="2_пречистенка.json", pdf="building-prech.pdf", pages=list(range(14,21)), plans={}, image="2_pre_bilding.png"),
]

COLORS = ["#C81340", "#295EA8", "#16836B", "#8A4FB0", "#D56B22"]

def clean_lines(value: str) -> list[str]:
    value = value.replace("•", "\n").replace(";", "\n")
    parts = value.splitlines() if "\n" in value else value.split(",")
    return [re.sub(r"\s+", " ", p).strip(" .,-") for p in parts if p.strip(" .,-")]

def capacity(general: str) -> int:
    match = re.search(r"Вместимость\s*[–-]\s*(.*?)(?:Площадь|$)", general, re.S | re.I)
    if not match: return 1
    segment = match.group(1)
    nums = [int(x) for x in re.findall(r"\d+", segment)]
    if not nums: return 1
    return sum(nums[:2]) if "+" in segment else nums[0]

def area(general: str) -> float | None:
    match = re.search(r"Площадь(?:\s+общая)?\s*[–-]\s*([\d,.]+)", general, re.I)
    return float(match.group(1).replace(",", ".")) if match else None

def floor_value(value: str, number: str, code: str) -> tuple[int, str]:
    display = value.strip() or "Этаж не указан"
    if "Антресоль" in display: return 1, "Антресоль"
    found = re.search(r"\d+", display)
    floor = int(found.group()) if found else (int(number[0]) if number[:1].isdigit() else 1)
    if code == "b5" and number == "316": floor, display = 3, "3 этаж"
    return floor, display if "этаж" in display.lower() or "Антресоль" in display else f"{floor} этаж"


def safe_slug(value: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return f"{readable or 'room'}-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:8]}"

def extract_page_media(reader: PdfReader, page_number: int, prefix: str) -> list[str]:
    images = list(reader.pages[page_number-1].images)[2:]
    result=[]
    for idx,image in enumerate(images[:3],1):
        ext = Path(image.name).suffix.lower() or ".jpg"
        name=f"rooms/{prefix}-{idx}{ext}"
        (MEDIA/name).parent.mkdir(parents=True,exist_ok=True)
        (MEDIA/name).write_bytes(image.data)
        result.append("/catalog/"+name.replace("\\","/"))
    return result

def main() -> None:
    if MEDIA.exists(): shutil.rmtree(MEDIA)
    (MEDIA / "buildings").mkdir(parents=True)
    (MEDIA / "plans").mkdir(parents=True)
    catalog={"buildings":[],"rooms":[]}
    # Reviewed passport bullets override the older intermediate transcription.
    verified = json.loads((ROOT / "backend" / "app" / "passport_equipment.json").read_text(encoding="utf-8"))
    passport_equipment = {(entry["building"], entry["number"]): entry["equipment"] for entry in verified["rooms"]}
    for bidx,source in enumerate(SOURCES):
        reader=PdfReader(PDF_DIR/source["pdf"])
        data=json.loads((OLD/"tr"/source["json"]).read_text(encoding="utf-8"))
        if len(data)!=len(source["pages"]): raise RuntimeError(f"Page mismatch for {source['code']}: {len(data)} != {len(source['pages'])}")
        building_image=f"/catalog/buildings/{source['code']}.png"
        shutil.copy2(OLD/"static"/"img"/"buildings"/source["image"], MEDIA/"buildings"/f"{source['code']}.png")
        catalog["buildings"].append({"code":source["code"],"name":source["name"],"address":source["address"],"image":building_image,"color":COLORS[bidx]})
        plan_paths={}
        for floor_name,page in source["plans"].items():
            imgs=list(reader.pages[page-1].images)[2:]
            if imgs:
                ext=Path(imgs[-1].name).suffix.lower() or ".png"
                rel=f"plans/{source['code']}-{safe_slug(floor_name)}{ext}"
                (MEDIA/rel).write_bytes(imgs[-1].data)
                plan_paths[page]="/catalog/"+rel
        for item,page in zip(data,source["pages"]):
            number=item["Number"].strip().replace("№ ","").replace("№","")
            cap=capacity(item.get("General", "")); floor,floor_display=floor_value(item.get("Floor", ""),number,source["code"])
            equipment = passport_equipment.get((source["name"], number), clean_lines(item.get("Technical", "")))
            usage = clean_lines(item.get("Usage", ""))
            photos=extract_page_media(reader,page,f"{source['code']}-{safe_slug(number)}")
            previous_plans=[(plan_page,value) for plan_page,value in plan_paths.items() if plan_page < page]
            plan=max(previous_plans,key=lambda pair:pair[0])[1] if previous_plans else None
            name=number if any(x in number.lower() for x in ("зал","сцена","пространство")) else f"Аудитория {number}"
            catalog["rooms"].append({"building_code":source["code"],"number":number,"name":name,"floor":floor,"floor_display":floor_display,"capacity":cap,"area":area(item.get("General","")),"equipment":equipment,"usage_options":usage,"description":re.sub(r"\s+"," ",item.get("General","")).strip(),"images":photos,"floor_plan":plan,"color":COLORS[bidx]})
    OUTPUT.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Created {len(catalog['buildings'])} buildings, {len(catalog['rooms'])} rooms")

if __name__ == "__main__": main()
