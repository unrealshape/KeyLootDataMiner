"""Reads the item level bonuses out of the game client's ItemBonusListLevelDelta table.

    python pipeline/extract_level_bonus.py --db2 PATH/ItemBonusListLevelDelta.db2 --build 12.1.0.69814

Every row says: the bonus list ID that moves an item's level by this many steps. The addon uses it to
show an item at the item level it drops with (a link carrying that bonus ID). Writes
pipeline/data/item_level_bonus.json; build.py turns that into Data/Bonus.lua.

The table is a WDC5 file with two 16-bit fields per row (the level delta, then the ID) and no
compression, so it is read directly.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "item_level_bonus.json"
LOWEST, HIGHEST = -100, 500
HEADER_FORMAT = "<IIIIIIIIIHHIIIIIII"
SECTION_SIZE = 40 + 8


def read_rows(data: bytes) -> dict:
    if data[:4] != b"WDC5":
        raise ValueError("not a WDC5 table")
    offset = 8 + 128
    (record_count, field_count, record_size, _strings, _hash, _layout, _min, _max, _locale,
     _flags, _index, _total, _bitpacked, _lookup, storage_size, common_size, pallet_size,
     sections) = struct.unpack_from(HEADER_FORMAT, data, offset)
    if field_count != 2 or record_size != 4 or sections != 1 or common_size or pallet_size:
        raise ValueError("the table does not have the layout this reader knows")
    offset += struct.calcsize(HEADER_FORMAT)
    section = struct.unpack_from("<QIIIIIIIII", data, offset)
    offset += SECTION_SIZE + 4 * field_count + storage_size
    rows = {}
    for index in range(section[2]):
        delta, bonus = struct.unpack_from("<hH", data, section[1] + record_size * index)
        rows[delta] = bonus
    if len(rows) != record_count:
        raise ValueError("duplicate level deltas in the table")
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db2", type=Path, required=True)
    parser.add_argument("--build", required=True)
    args = parser.parse_args(argv)
    try:
        rows = read_rows(args.db2.read_bytes())
    except (OSError, ValueError) as error:
        print(f"extract_level_bonus: {error}", file=sys.stderr)
        return 1
    kept = {str(d): b for d, b in sorted(rows.items()) if LOWEST <= d <= HIGHEST}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"build": args.build, "bonus": kept}, indent=1) + "\n", encoding="utf-8")
    print(f"{len(kept)} level steps from build {args.build} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
