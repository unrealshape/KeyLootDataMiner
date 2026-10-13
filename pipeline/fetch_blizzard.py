"""Fetches Blizzard's data and writes the datasets into build/datasets/.

    python pipeline/fetch_blizzard.py --out build/datasets [--part drops|mplus|all] [--pool 150] [--regions eu,us,kr,tw] [--specs class/spec,...] [--config pipeline/config.json]

  drops  -> blizzard-journal.json  where the season's items drop (Adventure Journal)
  specs  -> blizzard-specs.json    the game's specialization ids and our names for them
  mplus  -> blizzard-mplus.json    what the best Mythic+ players wear, their stats and talent builds (leaderboards of
                                   every region in --regions + profiles; cached in cache/stats.json and cache/talents.json)

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
DEFAULT_STATS_CACHE = Path(__file__).resolve().parent / "cache" / "stats.json"
DEFAULT_TALENTS_CACHE = Path(__file__).resolve().parent / "cache" / "talents.json"
DEFAULT_REGIONS = "eu,us,kr,tw"


def region_list(text, fallback):
    """The regions of --regions (lower case, no repeats); the config's `region` when the list is empty."""
    regions = list(dict.fromkeys(r.strip().lower() for r in (text or "").split(",") if r.strip()))
    return regions or [fallback]


def load_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=0, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def write(out: Path, name: str, dataset: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(validate(dataset), indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stats-cache", type=Path, default=DEFAULT_STATS_CACHE)
    parser.add_argument("--talents-cache", type=Path, default=DEFAULT_TALENTS_CACHE)
    parser.add_argument("--regions", default=DEFAULT_REGIONS,
                        help="regions whose Mythic+ leaderboards are read, comma separated (default eu,us,kr,tw; "
                             "empty: the config's `region`); a failing region is reported and skipped")
    parser.add_argument("--pool", type=int, default=150,
                        help="Mythic+ players read per specialization over all regions (default 150); the best top_per_spec of them are the mixed group")
    parser.add_argument("--specs", default=None,
                        help="limit the mplus part to these specializations, e.g. paladin/protection,druid/guardian")
    parser.add_argument("--part", choices=("drops", "specs", "mplus", "all"), default="all")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    try:
        client_id, secret = blizzard.read_credentials()
        client = blizzard.Client(client_id, secret, region=config.get("region", "eu"))
        if args.part in ("drops", "all"):
            drops = blizzard.fetch_drops(client, config["journal_tier"], config["raids"], config.get("dungeons"))
            write(args.out, "blizzard-journal.json", blizzard.dataset(drops))
            print(f"fetch_blizzard: {len(drops)} drop(s) from {len({(d['kind'], d['instance']) for d in drops})} instance(s)")
        if args.part in ("specs", "all"):
            specs = blizzard_gear.all_specs(client)
            write(args.out, "blizzard-specs.json", blizzard.make_dataset("blizzard-specs", specs=specs))
            print(f"fetch_blizzard: {len(specs)} specialization id(s)")
        if args.part in ("mplus", "all"):
            settings = config.get("mplus", {})
            specs, stats, players, problems = {}, [], [], []
            regions = region_list(args.regions, config.get("region", "eu"))
            clients = {r: client if r == client.region else blizzard.Client(client_id, secret, region=r) for r in regions}
            cache, talents = load_cache(args.stats_cache), load_cache(args.talents_cache)
            try:
                entries = blizzard_gear.fetch_entries(
                    client, top_per_spec=settings.get("top_per_spec", 50), periods=settings.get("periods", 2),
                    realm_limit=settings.get("realm_limit"), specs_out=specs, stats_out=stats, stats_cache=cache,
                    pool=args.pool, players_out=players, clients=clients, talents_cache=talents, problems=problems,
                    only_specs=[s.strip() for s in args.specs.split(",") if s.strip()] if args.specs else None)
            finally:
                save_cache(args.stats_cache, cache)
                save_cache(args.talents_cache, talents)
            for problem in problems:
                print(f"fetch_blizzard: region skipped: {problem}", file=sys.stderr)
            write(args.out, "blizzard-mplus.json",
                  blizzard.make_dataset("blizzard-mplus", entries=entries, specs=specs, stats=stats, players=players))
            print(f"fetch_blizzard: {len(entries)} Mythic+ entr(ies) for "
                  f"{len({(e['class'], e['spec']) for e in entries})} specialization(s)")
    except (blizzard.BlizzardError, KeyError, ValueError) as error:
        print(f"fetch_blizzard: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
