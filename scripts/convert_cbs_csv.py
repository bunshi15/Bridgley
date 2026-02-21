#!/usr/bin/env python3
"""One-time script: convert CBS locality CSV to localities.json.

Usage:
    python scripts/convert_cbs_csv.py path/to/cbs_localities.csv

The CSV is expected in windows-1255 encoding (Israel CBS download).
Output: app/core/bots/localities.json
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

# Russian transliterations for top ~60 Israeli cities
# Codes verified against CBS dataset
_RUSSIAN_NAMES: dict[int, str] = {
    # === Major cities ===
    5000: "Тель-Авив",           # תל אביב - יפו
    3000: "Иерусалим",           # ירושלים
    4000: "Хайфа",               # חיפה
    9000: "Беэр-Шева",           # באר שבע
    2600: "Эйлат",               # אילת
    7400: "Нетания",             # נתניה
    70:   "Ашдод",               # אשדוד
    7100: "Ашкелон",             # אשקלון
    7900: "Петах-Тиква",         # פתח תקווה
    8300: "Ришон ле-Цион",       # ראשון לציון
    6600: "Холон",               # חולון
    6100: "Бней-Брак",           # בני ברק
    6200: "Бат-Ям",              # בת ים
    8600: "Рамат-Ган",           # רמת גן
    6400: "Герцлия",             # הרצליה
    6900: "Кфар-Саба",           # כפר סבא
    8700: "Раанана",             # רעננה
    6300: "Гиватаим",            # גבעתיים
    2650: "Рамат-ха-Шарон",      # רמת השרון
    2640: "Рош-ха-Аин",          # ראש העין
    # === North ===
    7600: "Акко",                # עכו
    9100: "Нагария",             # נהריה
    7300: "Назарет",             # נצרת
    1061: "Ноф-ха-Галиль",      # נוף הגליל
    6700: "Тверия",              # טבריה
    7700: "Афула",               # עפולה
    1139: "Кармиэль",            # כרמיאל
    8000: "Цфат",                # צפת
    2800: "Кирьят-Шмона",        # קרית שמונה
    874:  "Мигдаль-ха-Эмек",     # מגדל העמק
    240:  "Йокнеам",             # יקנעם עילית
    # === Haifa metro ===
    6800: "Кирьят-Ата",          # קרית אתא
    9500: "Кирьят-Биалик",       # קרית ביאליק
    8200: "Кирьят-Моцкин",       # קרית מוצקין
    9600: "Кирьят-Ям",           # קרית ים
    2100: "Тират-Кармель",       # טירת כרמל
    2500: "Нешер",               # נשר
    2300: "Кирьят-Тивон",        # קרית טבעון
    6500: "Хадера",              # חדרה
    1020: "Ор-Акива",            # אור עקיבא
    # === Center ===
    8400: "Реховот",             # רחובות
    8500: "Рамла",               # רמלה
    7000: "Лод",                 # לוד
    1200: "Модиин",              # מודיעין-מכבים-רעות
    2610: "Бейт-Шемеш",         # בית שמש
    2620: "Кирьят-Оно",         # קרית אונו
    472:  "Абу-Гош",             # אבו גוש
    # === South ===
    2200: "Димона",              # דימונה
    2560: "Арад",                # ערד
    2630: "Кирьят-Гат",          # קרית גת
    1031: "Сдерот",              # שדרות
    31:   "Офаким",              # אופקים
    246:  "Нетивот",             # נתיבות
    1161: "Рахат",               # רהט
    831:  "Ерухам",              # ירוחם
    99:   "Мицпе-Рамон",         # מצפה רמון
    1271: "Лехавим",             # להבים
}


def convert(csv_path: str, output_path: str) -> None:
    with open(csv_path, "rb") as f:
        raw = f.read()

    text = raw.decode("windows-1255")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    header = rows[0]
    print(f"Header: {header}")
    print(f"Total rows (incl header): {len(rows)}")

    localities = []
    seen_codes: set[int] = set()

    for row in rows[1:]:
        if len(row) < 5:
            continue
        code_raw = row[0].strip()
        if not code_raw or code_raw == "0":
            continue
        code = int(code_raw)
        if code in seen_codes:
            continue
        seen_codes.add(code)

        he = row[1].strip()
        en = row[2].strip() or None
        region = int(row[3].strip()) if row[3].strip() else 0

        # Skip entries with region 0 (unknown)
        if region == 0:
            continue

        ru = _RUSSIAN_NAMES.get(code)

        localities.append({
            "code": code,
            "he": he,
            "en": en,
            "ru": ru,
            "region": region,
        })

    localities.sort(key=lambda x: x["code"])

    result = {
        "_meta": {
            "source": "Israel CBS localities",
            "version": "1.0",
            "count": len(localities),
        },
        "localities": localities,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Written {len(localities)} localities to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/convert_cbs_csv.py <csv_path>")
        sys.exit(1)

    csv_path = sys.argv[1]
    output_path = str(
        Path(__file__).resolve().parent.parent / "app" / "core" / "bots" / "localities.json"
    )
    convert(csv_path, output_path)
