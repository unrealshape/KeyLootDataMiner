# KeyLootMaster

A World of Warcraft addon (Retail 12.x) that shows where the best gear of your
class and specialization drops, for Mythic+ and the current raid.

The data comes from a daily pipeline, not from the addon itself:

```
sources (Blizzard API, Warcraft Logs, ...)
   -> one normalized JSON dataset per source      build/datasets/*.json
   -> pipeline/build.py merges and validates
   -> Lua data files in addon/KeyLootMaster/Data/ (one file per class)
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

## Status

Pipeline core and the three sources are in place and tested. The addon's
interface (the window, the tooltip line) is not built yet; a design sketch
exists. About half of the most-worn items have a journal drop location; tier
pieces, crafted gear and vendor items still need their own source.

## Develop

```
python -m unittest discover -s pipeline/tests -v
python pipeline/build.py --datasets build/datasets --out addon/KeyLootMaster/Data
```

Credentials live in `~/.config/<service>/credentials.env` locally and in the
repository secrets in Actions. They are never committed.
