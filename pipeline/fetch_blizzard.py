"""Fetches the season's drop locations and writes build/datasets/blizzard-journal.json.

    python pipeline/fetch_blizzard.py --out build/datasets [--config pipeline/config.json]

Exit status: 0 done, 1 the API or the credentials failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from klm.model import validate  # noqa: E402
from klm.sources import blizzard  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    try:
        client_id, secret = blizzard.read_credentials()
        client = blizzard.Client(client_id, secret, region=config.get("region", "eu"))
        drops = blizzard.fetch_drops(client, config["journal_tier"], config["raids"], config.get("dungeons"))
        result = validate(blizzard.dataset(drops))
    except (blizzard.BlizzardError, KeyError, ValueError) as error:
        print(f"fetch_blizzard: {error}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "blizzard-journal.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    instances = {(d["kind"], d["instance"]) for d in drops}
    print(f"fetch_blizzard: {len(drops)} drop(s) from {len(instances)} instance(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
