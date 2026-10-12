"""Fetches what the best raiders wear and writes build/datasets/wcl-raid.json.

    python pipeline/fetch_wcl.py --out build/datasets [--config pipeline/config.json]

Exit status: 0 done, 1 the API or the credentials failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from klm.model import validate  # noqa: E402
from klm.sources import wcl  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    settings = json.loads(args.config.read_text(encoding="utf-8"))["wcl"]
    try:
        client_id, secret = wcl.read_credentials()
        client = wcl.Client(client_id, secret)
        entries = wcl.fetch_entries(client, settings["zone"], settings.get("difficulty", 5),
                                    settings.get("top_per_spec", 100))
        dataset = validate({"source": "wcl-raid", "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "entries": entries, "drops": []})
    except (wcl.WclError, KeyError, ValueError) as error:
        print(f"fetch_wcl: {error}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "wcl-raid.json").write_text(
        json.dumps(dataset, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"fetch_wcl: {len(entries)} raid entr(ies) for {len({(e['class'], e['spec']) for e in entries})} specialization(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
