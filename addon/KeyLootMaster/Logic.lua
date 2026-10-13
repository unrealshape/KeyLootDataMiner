-- Pure data logic: no game API in here, so it can be tested outside the client.
--
-- The generated tables (Data/*.lua) are:
--   KeyLootMasterData[class][spec][content][slot] = { {item, share, sample}, ... }   best first
--   KeyLootMasterDrops[item]  = { {kind, instance, instanceName, encounter, encounterName}, ... }
--   KeyLootMasterItems[item]  = { s = "ch", l = ilvl, t = true }    s: c crit, h haste, m mastery, v versatility
--   KeyLootMasterSpecs[id]    = { class, spec }                      the game's specialization ids

local _, ns = ...
ns = ns or {}

ns.CONTENTS = { "mplus", "raid" }

-- The slots the lists use; both rings and both trinkets are one entry.
ns.SLOT_ORDER = { "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger", "trinket", "main_hand", "off_hand" }

-- The inventory slot ids that hold each (for "what do I wear already").
ns.INVENTORY_SLOTS = {
    head = { 1 }, neck = { 2 }, shoulder = { 3 }, back = { 15 }, chest = { 5 }, wrist = { 9 },
    hands = { 10 }, waist = { 6 }, legs = { 7 }, feet = { 8 }, finger = { 11, 12 },
    trinket = { 13, 14 }, main_hand = { 16 }, off_hand = { 17 },
}

-- Where an item comes from, most specific first.
ns.SOURCE_ORDER = { "dungeon", "raid", "catalyst", "crafted", "vendor", "other" }
ns.STATS = { { "c", "crit" }, { "h", "haste" }, { "m", "mastery" }, { "v", "versatility" } }

-- The upgrade tracks of the season: the item level of each of the six ranks.
ns.UPGRADE_TRACKS = {
    veteran = { 279, 282, 285, 289, 292, 295 },
    champion = { 292, 295, 298, 302, 305, 308 },
    hero = { 305, 308, 311, 315, 318, 321 },
    myth = { 318, 321, 324, 328, 331, 334 },
}
ns.TRACK_RANKS = 6

-- What a Mythic+ key level rewards: the track and rank of the item at the end of the dungeon and of
-- the Great Vault slot. Every level above the last one rewards the same as the last one.
ns.KEY_LEVELS = { 0, 2, 3, 4, 5, 6, 7, 8, 9, 10 }
ns.KEY_REWARDS = {
    run = {
        [0] = { "champion", 1 }, [2] = { "champion", 2 }, [3] = { "champion", 2 }, [4] = { "champion", 3 },
        [5] = { "champion", 4 }, [6] = { "hero", 1 }, [7] = { "hero", 1 }, [8] = { "hero", 2 },
        [9] = { "hero", 2 }, [10] = { "hero", 3 },
    },
    vault = {
        [2] = { "hero", 1 }, [3] = { "hero", 1 }, [4] = { "hero", 2 }, [5] = { "hero", 2 },
        [6] = { "hero", 3 }, [7] = { "hero", 4 }, [8] = { "hero", 4 }, [9] = { "hero", 4 },
        [10] = { "myth", 1 },
    },
}

--- "M0", "+4", "+10+" for the key levels of ns.KEY_LEVELS.
function ns.KeyLabel(level)
    if level == 0 then return "M0" end
    if level >= ns.KEY_LEVELS[#ns.KEY_LEVELS] then return "+" .. level .. "+" end
    return "+" .. level
end

--- The item level, track and rank a key level rewards; nil when it rewards nothing (a vault at M0).
function ns.KeyReward(level, vault)
    local entry = ns.KEY_REWARDS[vault and "vault" or "run"][math.min(level, ns.KEY_LEVELS[#ns.KEY_LEVELS])]
    if not entry then return nil end
    return ns.UPGRADE_TRACKS[entry[1]][entry[2]], entry[1], entry[2]
end

--- The item level, track and rank a Mythic+ dungeon item drops at for a key level. nil for everything
--- else: the raid list and items that do not drop in a dungeon.
function ns.DungeonLevel(item, content, level, vault)
    if content ~= "mplus" or not ns.KindsOf(item).dungeon then return nil end
    return ns.KeyReward(level, vault)
end

--- The key levels that reward the same, grouped: { { label = "+2-+3", ilvl, track, rank }, ... }.
function ns.KeyGroups(vault)
    local groups = {}
    for _, level in ipairs(ns.KEY_LEVELS) do
        local ilvl, track, rank = ns.KeyReward(level, vault)
        if ilvl then
            local last = groups[#groups]
            if last and last.ilvl == ilvl and last.track == track and last.rank == rank then
                last.to = level
            else
                groups[#groups + 1] = { from = level, to = level, ilvl = ilvl, track = track, rank = rank }
            end
        end
    end
    for _, group in ipairs(groups) do
        group.label = ns.KeyLabel(group.from)
        if group.to ~= group.from then group.label = group.label .. "-" .. ns.KeyLabel(group.to) end
    end
    return groups
end

-- Marks a player puts on items, in the order a right-click cycles through them.
ns.MARKS = { "must", "nice" }

--- The mark after `current` (nil = none): none -> must -> nice -> none.
function ns.NextMark(current)
    if not current then return ns.MARKS[1] end
    for index, mark in ipairs(ns.MARKS) do
        if mark == current then return ns.MARKS[index + 1] end
    end
    return nil
end

--- The bonus list ID that makes an item show the item level `target` (from the game's own level-step
--- table, Data/Bonus.lua), or nil when the item's own level or that step is unknown.
function ns.LevelBonus(item, target)
    local _, _, base = ns.FactsOf(item)
    local steps = KeyLootMasterBonus
    if not steps or not base or base <= 0 then return nil end
    return steps[target - base]
end

--- The item link of an item at an item level, for the tooltip; nil when no bonus is known.
function ns.LinkAtLevel(item, target)
    local bonus = ns.LevelBonus(item, target)
    if not bonus then return nil end
    return "item:" .. item .. string.rep(":", 11) .. ":1:" .. bonus
end

--- The tier below best in slot: how strongly the top players favour an item.
ns.STRONG_SHARE, ns.OPTION_SHARE = 0.4, 0.15
function ns.TierOf(share)
    if share >= ns.STRONG_SHARE then return "strong" end
    if share >= ns.OPTION_SHARE then return "option" end
    return nil
end

--- True for an item that drops in a Mythic+ dungeon (its tooltip lists what each key level rewards).
function ns.KeyTable(item)
    return ns.KindsOf(item).dungeon
end

--- The items that count as best in slot: the most worn one per slot, the two most worn for rings
--- and trinkets (set of item ids). Judged on the whole list, not on what the filters leave.
function ns.BisItems(class, spec, content)
    local set = {}
    for _, row in ipairs(ns.Rows(class, spec, content, nil, nil)) do
        local count = (row.slot == "finger" or row.slot == "trinket") and 2 or 1
        for index = 1, math.min(count, #row.items) do set[row.items[index].item] = true end
    end
    return set
end

-- The stats page: the secondary stats compete for the player's points, the minor ones come on top.
ns.MAIN_STATS = { { "c", "Crit" }, { "h", "Haste" }, { "m", "Mastery" }, { "v", "Versatility" } }
ns.MINOR_STATS = { { "leech", "Leech" }, { "avoidance", "Avoidance" }, { "speed", "Speed" } }

--- The average stats of the top players of a specialization, or nil:
--- { n = players, c = {rating, percent}, h = ..., m = ..., v = ..., leech = ..., avoidance = ..., speed = ... }
--- (KeyLootMasterStats[class][spec], Data/Stats.lua).
function ns.StatsOf(class, spec)
    local all = KeyLootMasterStats
    return all and all[class] and all[class][spec] or nil
end

--- The stats of a group ordered from the highest rating down: { { key, name, rating, percent }, ... }.
--- Ties keep the order of the group.
function ns.StatRanking(stats, group)
    local list = {}
    for index, pair in ipairs(group) do
        local value = stats[pair[1]] or { 0, 0 }
        list[#list + 1] = { key = pair[1], name = pair[2], rating = value[1] or 0, percent = value[2] or 0, order = index }
    end
    table.sort(list, function(a, b)
        if a.rating ~= b.rating then return a.rating > b.rating end
        return a.order < b.order
    end)
    return list
end

local function tables()
    return KeyLootMasterData or {}, KeyLootMasterDrops or {}, KeyLootMasterItems or {}, KeyLootMasterSpecs or {}
end

--- "paladin", "protection" for a specialization id, or nil.
function ns.SpecKeyOf(specId)
    local _, _, _, specs = tables()
    local entry = specs[specId]
    if entry then return entry[1], entry[2] end
    return nil
end

local function title(key)
    return (key:gsub("%-", " "):gsub("(%a)([%w']*)", function(first, rest) return first:upper() .. rest end))
end
ns.Title = title

--- Every specialization the data holds: { { id, class, spec, label }, ... } by class then spec.
function ns.SpecList()
    local data, _, _, specs = tables()
    local list = {}
    for id, entry in pairs(specs) do
        if data[entry[1]] and data[entry[1]][entry[2]] then
            list[#list + 1] = { id = id, class = entry[1], spec = entry[2],
                label = title(entry[1]) .. " - " .. title(entry[2]) }
        end
    end
    table.sort(list, function(a, b) return a.label < b.label end)
    return list
end

--- The drop records of an item (possibly empty).
function ns.DropsOf(item)
    local _, drops = tables()
    return drops[item] or {}
end

--- The kinds of source an item has; an item the data does not know counts as "other".
function ns.KindsOf(item)
    local kinds, found = {}, false
    for _, drop in ipairs(ns.DropsOf(item)) do
        kinds[drop.kind] = true
        found = true
    end
    if not found then kinds.other = true end
    return kinds
end

--- The one line that says where an item comes from, plus how many other places there are.
function ns.SourceLabel(item)
    local drops = ns.DropsOf(item)
    if #drops == 0 then return nil, 0 end
    local best, rank = nil, math.huge
    for _, drop in ipairs(drops) do
        for index, kind in ipairs(ns.SOURCE_ORDER) do
            if kind == drop.kind and index < rank then best, rank = drop, index end
        end
    end
    best = best or drops[1]
    local text = best.instanceName
    if best.encounterName and best.encounterName ~= "" then text = text .. " - " .. best.encounterName end
    return text, #drops - 1
end

--- The secondary-stat letters of an item ("" when unknown) and whether it is a tier piece.
function ns.FactsOf(item)
    local _, _, items = tables()
    local facts = items[item]
    if not facts then return "", false, 0 end
    return facts.s or "", facts.t == true, facts.l or 0
end

--- Whether an item passes the filters: { source = kind|nil, stats = "ch"|"" (all of them), missing = bool }.
--- `equipped` is a set of the item ids worn now.
function ns.Passes(item, filters, equipped)
    filters = filters or {}
    if filters.source and not ns.KindsOf(item)[filters.source] then return false end
    if filters.stats and filters.stats ~= "" then
        local have = ns.FactsOf(item)
        for letter in filters.stats:gmatch(".") do
            if not have:find(letter, 1, true) then return false end
        end
    end
    if filters.farmable and not ns.KindsOf(item)[filters.farmable] then return false end
    if filters.missing and equipped and equipped[item] then return false end
    return true
end

--- The rows of the window: one per slot, the items that pass the filters, best first.
--- { { slot = "head", items = { {item, share, sample}, ... } }, ... }
function ns.Rows(class, spec, content, filters, equipped)
    local data = tables()
    local lists = data[class] and data[class][spec] and data[class][spec][content] or {}
    local rows = {}
    for _, slot in ipairs(ns.SLOT_ORDER) do
        local items = {}
        for _, entry in ipairs(lists[slot] or {}) do
            if ns.Passes(entry[1], filters, equipped) then
                items[#items + 1] = { item = entry[1], share = entry[2], sample = entry[3] }
            end
        end
        rows[#rows + 1] = { slot = slot, items = items }
    end
    return rows
end

--- item -> { mplus = share, raid = share } over every slot of one specialization (for tooltips).
function ns.ShareIndex(class, spec)
    local data = tables()
    local index = {}
    local contents = data[class] and data[class][spec]
    if not contents then return index end
    for _, content in ipairs(ns.CONTENTS) do
        for _, entries in pairs(contents[content] or {}) do
            for _, entry in ipairs(entries) do
                local held = index[entry[1]] or {}
                held[content] = math.max(held[content] or 0, entry[2])
                index[entry[1]] = held
            end
        end
    end
    return index
end

function ns.Percent(share)
    return string.format("%d%%", math.floor(share * 100 + 0.5))
end

--- Letters of the secondary stats as one readable string, e.g. "ch" -> "Crit, Haste".
function ns.StatText(letters, names)
    local out = {}
    for _, pair in ipairs(ns.STATS) do
        if letters:find(pair[1], 1, true) then out[#out + 1] = names and names[pair[1]] or pair[2] end
    end
    return table.concat(out, ", ")
end

return ns
