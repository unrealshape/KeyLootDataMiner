"""Fetches Blizzard's data and writes the datasets into build/datasets/.

    python pipeline/fetch_blizzard.py --out build/datasets [--part drops|mplus|all] [--config pipeline/config.json]

  drops  -> blizzard-journal.json  where the season's items drop (Adventure Journal)
  mplus  -> blizzard-mplus.json    what the best Mythic+ players wear (leaderboards + profiles)

Exit status: 0 done, 1 the API or the credentials failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from klm.model import validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"


def write(out: Path, name: str, dataset: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(validate(dataset), indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--part", choices=("drops", "mplus", "all"), default="all")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    try:
        client_id, secret = blizzard.read_credentials()
        client = blizzard.Client(client_id, secret, region=config.get("region", "eu"))
        if args.part in ("drops", "all"):
            drops = blizzard.fetch_drops(client, config["journal_tier"], config["raids"], config.get("dungeons"))
            write(args.out, "blizzard-journal.json", blizzard.dataset(drops))
            print(f"fetch_blizzard: {len(drops)} drop(s) from {len({(d['kind'], d['instance']) for d in drops})} instance(s)")
        if args.part in ("mplus", "all"):
            settings = config.get("mplus", {})
            entries = blizzard_gear.fetch_entries(
                client, top_per_spec=settings.get("top_per_spec", 50), periods=settings.get("periods", 2),
                realm_limit=settings.get("realm_limit"))
            write(args.out, "blizzard-mplus.json", blizzard.make_dataset("blizzard-mplus", entries=entries))
            print(f"fetch_blizzard: {len(entries)} Mythic+ entr(ies) for "
                  f"{len({(e['class'], e['spec']) for e in entries})} specialization(s)")
    except (blizzard.BlizzardError, KeyError, ValueError) as error:
        print(f"fetch_blizzard: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
