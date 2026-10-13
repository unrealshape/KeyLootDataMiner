# KeyLootDataMiner

The data miner of the World of Warcraft addon KeyLootMaster, which shows where the best gear of your
class and specialization drops, for Mythic+ and the current raid. The data comes from this pipeline:

```
sources (Blizzard API, Warcraft Logs, ...)
   -> one normalized JSON dataset per source      build/datasets/*.json
   -> pipeline/build.py merges and validates
   -> Lua data files for the addon (one file per class), pushed to the KeyLootMaster repository
```

- **entries**: how often the best players of a class and specialization wear an item, per content and slot.
- **drops**: where an item comes from (dungeon or raid boss, crafted, vendor).
- A new source only has to deliver the dataset shape in `pipeline/klm/model.py`;
  `merge.py` weights shares by sample size and keeps which source contributed.

## Sources

| Source | Delivers | Script |
| --- | --- | --- |
| Blizzard Adventure Journal | where the season's dungeon and raid items drop | `pipeline/fetch_blizzard.py --part drops` |
| Blizzard leaderboards + profiles | what the best Mythic+ players wear (top 50 per specialization) | `pipeline/fetch_blizzard.py --part mplus` |
| Warcraft Logs rankings | what the best raiders wear (top 100 per specialization) | `pipeline/fetch_wcl.py` |

Season, raid and sample sizes are set in `pipeline/config.json`.

| Blizzard item API | secondary stats, tier set, item level; names a source (Catalyst, crafted, other) for items the journal lacks | `pipeline/fetch_items.py` |

## The addon

The addon itself lives in its own repository, [KeyLootMaster](https://github.com/unrealshape/KeyLootMaster)
(what it can do, install, releases). This repository only produces its data.

## How a run ends in a release

`.github/workflows/daily.yml` (twice a week and on demand) reads the sources, merges them and writes the Lua
files into a checkout of KeyLootMaster (`master/KeyLootMaster/Data`). The run pushes them there with a deploy
key (secret `ADDON_DEPLOY_KEY`). The push starts the release workflow of KeyLootMaster: addon tests, a new
version `vYYYY.MM.DD.<run>`, the zip as a release asset.

## Develop

```
python -m unittest discover -s pipeline/tests -v
python pipeline/build.py --datasets build/datasets --out ../KeyLootMaster/KeyLootMaster/Data
```

Credentials live in `~/.config/<service>/credentials.env` locally and in the
repository secrets in Actions. They are never committed.

## License

MIT, see [LICENSE](LICENSE).
