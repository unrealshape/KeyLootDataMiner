"""Merges the sources' datasets and writes the addon's Lua data files.

    python pipeline/build.py --datasets build/datasets --out addon/KeyLootMaster/Data

`--datasets` holds one JSON file per source (shape: klm/model.py). Every
dataset is validated first; one that is not well formed stops the build before
anything is written, so a bad source can never leave half a data set behind.
The output folder is replaced file by file only when a file's text changed.

Exit status: 0 done, 1 a dataset is malformed or none was found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from klm import lua  # noqa: E402
from klm.merge import derive_mplus, merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402

DEFAULT_TOP = 8
DEFAULT_MAX_RAID_ITEMS = 1
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
BONUS_PATH = Path(__file__).resolve().parent / "data" / "item_level_bonus.json"


def load_datasets(folder: Path) -> list:
    datasets = []
    for path in sorted(folder.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            dataset = json.load(handle)
        try:
            validate(dataset)
        except DatasetError as error:
            raise DatasetError(f"{path.name}: {error}") from error
        datasets.append(dataset)
    return datasets


def render(merged: dict, top: int, group_size: int = 50, max_raid_items: int = DEFAULT_MAX_RAID_ITEMS) -> dict:
    gear_source = merged
    merged = derive_mplus(merged, group_size, max_raid_items)
    files = lua.class_files(merged, top)
    files["Drops.lua"] = lua.drops_file(merged)
    files["Items.lua"] = lua.items_file(merged, top)
    files["Specs.lua"] = lua.specs_file(merged)
    files["Meta.lua"] = lua.meta_file(merged, top)
    if merged.get("stats"):
        files["Stats.lua"] = lua.stats_file(merged)
    gear_text = lua.gear_file(gear_source, group_size, max_raid_items)
    if gear_text:
        files["Gear.lua"] = gear_text
    if BONUS_PATH.is_file():
        files["Bonus.lua"] = lua.bonus_file(json.loads(BONUS_PATH.read_text(encoding="utf-8"))["bonus"])
    files["Data.xml"] = lua.manifest(sorted(files))
    return files


def write_changed(out: Path, files: dict) -> list:
    """Writes the files whose text changed; returns their names."""
    out.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, text in sorted(files.items()):
        target = out / name
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        target.write_text(text, encoding="utf-8", newline="\n")
        changed.append(name)
    for stale in sorted(list(out.glob("*.lua")) + list(out.glob("*.xml"))):
        if stale.name not in files:
            stale.unlink()
            changed.append(stale.name + " (removed)")
    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--max-raid-items", type=int, default=DEFAULT_MAX_RAID_ITEMS,
                        help="a pure Mythic+ player wears at most this many raid items (default 1)")
    parser.add_argument("--group-size", type=int, default=None,
                        help="players in the Mythic+ group (default: mplus.top_per_spec of the config, 50)")
    args = parser.parse_args(argv)
    group_size = args.group_size
    if group_size is None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.is_file() else {}
        group_size = config.get("mplus", {}).get("top_per_spec", 50)
    try:
        datasets = load_datasets(args.datasets)
    except (DatasetError, OSError, json.JSONDecodeError) as error:
        print(f"build: {error}", file=sys.stderr)
        return 1
    if not datasets:
        print(f"build: no dataset in {args.datasets}", file=sys.stderr)
        return 1
    changed = write_changed(args.out, render(merge(datasets), args.top, group_size, args.max_raid_items))
    print(f"build: {len(datasets)} dataset(s), {len(changed)} file(s) changed")
    for name in changed:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
