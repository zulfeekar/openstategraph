#!/usr/bin/env python3
"""Regenerates workflows/tabular-analytics/data/vgsales.csv — SYNTHETIC data.

The real Kaggle "Video Game Sales" dataset is scraped from VGChartz and is not
clearly redistributable, so this repo ships a generated stand-in instead
(decision on ticket 41): same columns, realistic shapes, deterministic seed,
and internally consistent — Global_Sales is exactly the sum of the regions,
which the real scrape famously is not. Titles are invented; any resemblance
to a real game is coincidence.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "workflows/tabular-analytics/data/vgsales.csv"
ROWS = 300

PLATFORMS = ["NES", "SNES", "N64", "GC", "Wii", "WiiU", "Switch", "PS", "PS2", "PS3", "PS4", "PS5", "X360", "XOne", "PC", "GBA", "DS", "3DS"]
GENRES = ["Action", "Adventure", "Fighting", "Misc", "Platform", "Puzzle", "Racing", "Role-Playing", "Shooter", "Simulation", "Sports", "Strategy"]
PUBLISHERS = ["Nintendo", "Sony Interactive", "Microsoft Studios", "Electronic Arts", "Activision", "Ubisoft", "Sega", "Capcom", "Square Enix", "Take-Two", "Konami", "Bandai Namco"]
ADJ = ["Super", "Mega", "Turbo", "Galactic", "Shadow", "Crystal", "Neon", "Iron", "Solar", "Phantom", "Royal", "Lost"]
NOUN = ["Quest", "Racer", "Arena", "Legends", "Odyssey", "Tactics", "Kingdom", "Rally", "Saga", "Frontier", "Blitz", "Chronicles"]
SUFFIX = ["", " II", " III", " IV", " X", " Deluxe", " World", " Online", " Zero", " Remastered"]


def main() -> None:
    rng = random.Random(41)  # the ticket number, for the audit trail
    seen: set[str] = set()
    rows = []
    for _ in range(ROWS):
        while True:
            name = f"{rng.choice(ADJ)} {rng.choice(NOUN)}{rng.choice(SUFFIX)}"
            if name not in seen:
                seen.add(name)
                break
        # Log-ish sales distribution: a few hits, a long tail.
        scale = rng.choice([0.05, 0.1, 0.3, 0.8, 2.0, 6.0])
        na = round(rng.uniform(0.0, 1.0) * scale, 2)
        eu = round(rng.uniform(0.0, 0.8) * scale, 2)
        jp = round(rng.uniform(0.0, 0.6) * scale, 2)
        other = round(rng.uniform(0.0, 0.3) * scale, 2)
        rows.append({
            "Name": name,
            "Platform": rng.choice(PLATFORMS),
            "Year": rng.randint(1985, 2024),
            "Genre": rng.choice(GENRES),
            "Publisher": rng.choice(PUBLISHERS),
            "NA_Sales": na,
            "EU_Sales": eu,
            "JP_Sales": jp,
            "Other_Sales": other,
            "Global_Sales": round(na + eu + jp + other, 2),
        })

    rows.sort(key=lambda r: r["Global_Sales"], reverse=True)
    with OUT.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Rank", *rows[0].keys()])
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            writer.writerow({"Rank": rank, **row})
    print(f"wrote {len(rows)} synthetic rows to {OUT}")


if __name__ == "__main__":
    main()
