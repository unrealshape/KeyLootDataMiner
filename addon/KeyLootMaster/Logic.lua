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
