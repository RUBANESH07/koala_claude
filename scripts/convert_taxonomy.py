"""
Convert data/taxonomy.csv to data/taxonomy.json.

CSV columns:
  Display Resort DB ID, Display Resort Name, Technical Resort Name (Aliases),
  Display Unit DB ID, Display Unit Name, Technical Unit Name (Aliases)

Aliases are newline-separated within each cell.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = ROOT / "data" / "taxonomy.csv"
OUTPUT_JSON = ROOT / "data" / "taxonomy.json"


def parse_aliases(cell: str) -> list[str]:
    """Split a newline-separated alias cell into a cleaned list."""
    if not cell:
        return []
    return [a.strip() for a in cell.splitlines() if a.strip()]


def convert(input_path: Path = INPUT_CSV, output_path: Path = OUTPUT_JSON) -> list[dict]:
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    records = []
    with input_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            records.append({
                "resort_db_id": row["Display Resort DB ID"].strip(),
                "display_resort_name": row["Display Resort Name"].strip(),
                "resort_aliases": parse_aliases(row["Technical Resort Name (Aliases)"]),
                "unit_db_id": row["Display Unit DB ID"].strip(),
                "display_unit_name": row["Display Unit Name"].strip(),
                "unit_aliases": parse_aliases(row["Technical Unit Name (Aliases)"]),
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    print(f"Converted {len(records)} rows → {output_path}")
    return records


if __name__ == "__main__":
    convert()
