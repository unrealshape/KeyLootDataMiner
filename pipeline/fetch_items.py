"""Reads the facts of the items the addon shows and names a source for every item
the Adventure Journal does not list (Catalyst, crafted, other).

    python pipeline/fetch_items.py --datasets build/datasets [--cache pipeline/cache/items.json]

Needs the entries and the journal drops in `--datasets` already (the other
fetch scripts), and writes build/datasets/blizzard-items.json. The cache keeps
what the item API said, so a daily run reads only the items that are new.

Exit status: 0 done, 1 the API or the credentials failed or nothing to work on.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import DEFAULT_TOP, load_datasets  # noqa: E402
from klm.merge import merge  # noqa: E402
from klm.lua import shown_items  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_catalyst, blizzard_items  # noqa: E402

DEFAULT_CACHE = Path(__file__).resolve().parent / "cache" / "items.json"


def new_sections(client, merged, shown, cache):
    """The Catalyst sources and the tier sets. They are extras: whatever goes wrong here is reported and leaves
    the rest of the run alone (the addon shows them only when the data has them)."""
    try:
        dungeon = {d["item"] for d in merged["drops"] if d["kind"] == "dungeon"}
        blizzard_items.refresh(client, dungeon - shown, cache)
        sections = {"catalyst": blizzard_catalyst.catalyst_records(merged["drops"], cache),
                    "tierset": blizzard_catalyst.tierset_records(client, merged["entries"], cache)}
        validate({"source": "check", "generated": "check", **sections})
        return sections
    except (blizzard.BlizzardError, DatasetError, KeyError, ValueError, TypeError, AttributeError) as error:
        print(f"fetch_items: Catalyst sources and tier sets skipped: {error}", file=sys.stderr)
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    args = parser.parse_args(argv)
    try:
        sources = [d for d in load_datasets(args.datasets) if d["source"] != "blizzard-items"]
        merged = merge(sources)
        shown = shown_items(merged, args.top)
        if not shown:
            print("fetch_items: no entries to work on; run the other fetch scripts first", file=sys.stderr)
            return 1
        cache = json.loads(args.cache.read_text(encoding="utf-8")) if args.cache.exists() else {}
        client_id, secret = blizzard.read_credentials()
        client = blizzard.Client(client_id, secret)
        read = blizzard_items.refresh(client, shown, cache)
        recipes = blizzard_items.recipe_professions(client)
        journal = {d["item"] for d in merged["drops"]}
        drops = blizzard_items.other_drops(shown, journal, cache, recipes)
        items = blizzard_items.item_records(shown, cache, blizzard_items.themes(cache))
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dataset = validate({"source": "blizzard-items", "generated": stamp, "entries": [], "drops": drops,
                            "items": items, "specs": {}, **new_sections(client, merged, shown, cache)})
    except (blizzard.BlizzardError, DatasetError, KeyError, ValueError, OSError) as error:
        print(f"fetch_items: {error}", file=sys.stderr)
        return 1
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps(cache, indent=0, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
    (args.datasets / "blizzard-items.json").write_text(
        json.dumps(dataset, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    kinds = {}
    for drop in drops:
        kinds[drop["kind"]] = kinds.get(drop["kind"], 0) + 1
    print(f"fetch_items: {len(shown)} shown item(s), {read} read from the API, no journal drop: {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
