#!/usr/bin/env python3
"""
Generate a CSV of mock patient appointment records.

Columns: patient_id, name, phone, address, appointment_datetime, attended
- attended defaults to False for every row.
- address is a residential-style Nairobi address: invented house number on a real
  street/estate, with that area's postal code (geocodes in Google Maps).
- Uses only the Python standard library (works offline).

Usage:
    python generate_patients.py                      # 10 rows -> patients.csv
    python generate_patients.py -n 200 -o out.csv    # 200 rows -> out.csv
    python generate_patients.py --seed 42            # reproducible output
    python generate_patients.py --days 14            # appointments within next 14 days
"""

import argparse
import csv
import random
from datetime import datetime, timedelta

FIRST_NAMES = [
    "Amina", "Kwame", "Fatima", "Joseph", "Grace", "Samuel", "Aisha", "David",
    "Mary", "Ibrahim", "Esther", "Daniel", "Ruth", "Peter", "Zainab", "John",
    "Halima", "Moses", "Sarah", "Emmanuel", "Leila", "Omar", "Nadia", "Tobi",
    "Noor", "Elena", "Carlos", "Priya", "Ravi", "Mei", "Wei", "Ana",
]

LAST_NAMES = [
    "Okafor", "Mensah", "Banda", "Mwangi", "Diallo", "Nkosi", "Otieno", "Kamau",
    "Abubakar", "Phiri", "Osei", "Traore", "Achieng", "Moyo", "Haddad", "Rahman",
    "Silva", "Santos", "Kumar", "Sharma", "Chen", "Li", "Garcia", "Lopez",
]

# (street, estate, postal code): real Nairobi streets/estates with area postal codes.
# House numbers are invented, so no address belongs to a real, identifiable person.
STREETS = [
    ("Argwings Kodhek Road", "Kilimani", "00100"),
    ("Ngong Road", "Kilimani", "00100"),
    ("Ragati Road", "Upper Hill", "00100"),
    ("Mbaazi Avenue", "Lavington", "00100"),
    ("James Gichuru Road", "Lavington", "00100"),
    ("Othaya Road", "Kileleshwa", "00100"),
    ("Kibera Drive", "Kibera", "00100"),
    ("Rhapta Road", "Westlands", "00800"),
    ("Limuru Road", "Parklands", "00623"),
    ("Ngara Road", "Ngara", "00600"),
    ("Karen Road", "Karen", "00502"),
    ("Bogani Road", "Karen", "00502"),
    ("Langata Road", "Langata", "00509"),
    ("Muhoho Avenue", "South C", "00200"),
    ("Plains Road", "South B", "00200"),
    ("Thika Road", "Kasarani", "00618"),
    ("Kasarani-Mwiki Road", "Kasarani", "00618"),
    ("Mombasa Road", "Embakasi", "00515"),
    ("Jogoo Road", "Donholm", "00518"),
    ("General Waruinge Street", "Eastleigh", "00610"),
]

CLINIC_HOURS = range(8, 17)          # 8:00 to 16:xx
SLOT_MINUTES = (0, 30)               # 30-minute appointment slots


CUSTOM_ROWS = [
    {"patient_id": "P99998", "name": "Angel Li", "phone": "+001-786-395-6618",
     "address": "27 Argwings Kodhek Road, Kilimani, Nairobi 00100",
     "appointment_datetime": "2026-10-01 14:30", "attended": False},
]


def make_patient_id(index: int) -> str:
    return f"P{index:05d}"


def make_phone(rng: random.Random) -> str:
    # Clearly fake format; 555 prefix avoids colliding with real numbers.
    return f"+000-555-{rng.randint(0, 999):03d}-{rng.randint(0, 9999):04d}"


def make_address(rng: random.Random) -> str:
    street, estate, postal = rng.choice(STREETS)
    return f"{rng.randint(1, 120)} {street}, {estate}, Nairobi {postal}"


def make_appointment(rng: random.Random, start: datetime, days: int) -> datetime:
    while True:
        day = start + timedelta(days=rng.randint(0, days - 1))
        if day.weekday() < 5:  # weekdays only
            break
    return day.replace(
        hour=rng.choice(CLINIC_HOURS),
        minute=rng.choice(SLOT_MINUTES),
        second=0,
        microsecond=0,
    )


def generate(n: int, days: int, seed: int | None) -> list[dict]:
    rng = random.Random(seed)
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for i in range(1, n + 1 - len(CUSTOM_ROWS)):
        rows.append({
            "patient_id": make_patient_id(i),
            "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "phone": make_phone(rng),
            "address": make_address(rng),
            "appointment_datetime": make_appointment(rng, start, days).strftime("%Y-%m-%d %H:%M"),
            "attended": False,
        })
    rows.extend(CUSTOM_ROWS)
    rows.sort(key=lambda r: r["appointment_datetime"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mock patient appointment CSV.")
    parser.add_argument("-n", "--num", type=int, default=10, help="number of patients (default 10)")
    parser.add_argument("-o", "--output", default="patients.csv", help="output CSV path")
    parser.add_argument("--days", type=int, default=30, help="schedule window in days from today (default 30)")
    parser.add_argument("--seed", type=int, default=None, help="random seed for reproducible output")
    args = parser.parse_args()

    rows = generate(args.num, args.days, args.seed)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} records to {args.output}")


if __name__ == "__main__":
    main()