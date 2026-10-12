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

| Blizzard item API | secondary stats, tier set, item level; names a source (Catalyst, crafted, other) for items the journal lacks | `pipeline/fetch_items.py` |

## The addon

`/klm` (or the addon list button next to the minimap) opens the window:

- the best items per slot for your specialization (or any other), Mythic+ or raid;
- where each drops (dungeon and boss, raid boss, Catalyst, crafted, other) and a button into the Adventure Guide;
- **filters**: by source, by secondary stats (Crit, Haste, Mastery, Versatility; an item must carry all that are ticked), and "only missing" (hides what you wear);
- a line in every item tooltip with the share of top players who wear it; `/klm tooltip` switches it off.

## Status

Pipeline, sources and the addon are in place and tested outside the game (the addon against a
stub of the game API with the real data). It has not been run in the game yet.
Tier pieces are named by the set they belong to; items of other classes' sets may show as
"other source".

## Install for testing

Copy `addon/KeyLootMaster` into `World of Warcraft/_retail_/Interface/AddOns/`.

## Develop

```
python -m unittest discover -s pipeline/tests -v
python pipeline/build.py --datasets build/datasets --out addon/KeyLootMaster/Data
```

Credentials live in `~/.config/<service>/credentials.env` locally and in the
repository secrets in Actions. They are never committed.
