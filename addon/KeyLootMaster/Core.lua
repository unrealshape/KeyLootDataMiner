-- Startup, saved settings, the player's specialization and equipment, the slash command.
local ADDON, ns = ...

local L = ns.L

KeyLootMasterDB = KeyLootMasterDB or {}

local DEFAULTS = {
    content = "mplus",          -- "mplus" | "raid"
    source = nil,               -- a kind from ns.SOURCE_ORDER, or nil for all
    stats = "",                 -- letters of the secondary stats every item must carry
    missing = false,            -- hide what the player wears already
    spec = nil,                 -- a specialization id, or nil for the player's own
    tooltip = true,             -- the KeyLootMaster line in item tooltips
    farmable = true,            -- only items that drop in the shown content (dungeon for Mythic+, raid for Raid)
    group = "dungeon",         -- the players the Mythic+ lists come from: "dungeon" (do dungeons) or "all" (every top player)
    keyLevel = 0,               -- the key level the item levels show (one of ns.KEY_LEVELS)
    vault = false,              -- show the Great Vault reward of that key level instead of the end of the dungeon
    minimapHide = false,        -- hide the minimap button
    minimapAngle = 215,         -- where the minimap button sits on the rim, in degrees
}
ns.DEFAULTS = DEFAULTS

--- The saved settings with the defaults filled in.
function ns.Settings()
    local db = KeyLootMasterDB
    for key, value in pairs(DEFAULTS) do
        if db[key] == nil then db[key] = value end
    end
    if db.content ~= "mplus" and db.content ~= "raid" then db.content = "mplus" end
    local known = false
    for _, level in ipairs(ns.KEY_LEVELS) do if level == db.keyLevel then known = true end end
    if not known then db.keyLevel = 0 end
    if type(db.marks) ~= "table" then db.marks = {} end
    if db.group ~= "dungeon" and db.group ~= "all" then db.group = "dungeon" end
    return db
end

-- The settings that belong to one specialization (everything that filters the list).
local PROFILE_KEYS = { "content", "source", "stats", "missing", "farmable", "keyLevel", "vault", "group" }

--- Makes the filters those of a specialization ("paladin-holy"): the ones in use are put away for the
--- specialization shown before, and the saved ones of this one are brought back. A specialization
--- without saved filters keeps the ones in use.
function ns.UseProfile(specKey)
    local db = ns.Settings()
    if not specKey or db.profileKey == specKey then return end
    db.profiles = db.profiles or {}
    if db.profileKey then
        local saved = {}
        for _, key in ipairs(PROFILE_KEYS) do saved[key] = db[key] end
        db.profiles[db.profileKey] = saved
    end
    local wanted = db.profiles[specKey]
    if wanted then
        for _, key in ipairs(PROFILE_KEYS) do db[key] = wanted[key] end
    end
    db.profileKey = specKey
    ns.Settings()
end

--- The player's current specialization id, or nil (no specialization yet).
function ns.PlayerSpecId()
    local index = GetSpecialization and GetSpecialization()
    if not index then return nil end
    local id = GetSpecializationInfo(index)
    return id
end

--- The specialization shown: the one chosen in the window, else the player's own.
function ns.ShownSpec()
    local db = ns.Settings()
    local id = db.spec or ns.PlayerSpecId()
    if not id then return nil end
    local class, spec = ns.SpecKeyOf(id)
    return id, class, spec
end

--- Set of the item ids the player wears now.
function ns.EquippedItems()
    local worn = {}
    for _, slots in pairs(ns.INVENTORY_SLOTS) do
        for _, slot in ipairs(slots) do
            local id = GetInventoryItemID and GetInventoryItemID("player", slot)
            if id then worn[id] = true end
        end
    end
    return worn
end

--- The item level of what the player wears in a slot of the lists (the lower of two for rings and
--- trinkets); 0 when the slot is empty.
function ns.WornItemLevel(slotKey)
    local lowest
    for _, slot in ipairs(ns.INVENTORY_SLOTS[slotKey] or {}) do
        local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
        local level = 0
        if link then
            local detailed = (C_Item and C_Item.GetDetailedItemLevelInfo) or GetDetailedItemLevelInfo
            level = detailed and detailed(link) or 0
        end
        lowest = lowest and math.min(lowest, level) or level
    end
    return lowest or 0
end

--- The mark the player put on an item for a specialization key ("paladin-holy"), or nil.
function ns.MarkOf(specKey, item)
    local held = ns.Settings().marks[specKey]
    return held and held[item] or nil
end

--- Moves an item to its next mark (see ns.NextMark) and returns it.
function ns.CycleMark(specKey, item)
    local marks = ns.Settings().marks
    marks[specKey] = marks[specKey] or {}
    local mark = ns.NextMark(marks[specKey][item])
    marks[specKey][item] = mark
    return mark
end

--- The enchantment id on what the player wears in a slot of the lists (the first of two for rings),
--- nil when nothing is worn there.
function ns.OwnEnchantId(slotKey)
    for _, slot in ipairs(ns.INVENTORY_SLOTS[slotKey] or {}) do
        local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
        if type(link) == "string" then
            local id = link:match("item:%d+:(%d*)")
            return tonumber(id) or 0
        end
    end
    return nil
end

--- The gems the player wears, counted by color: { meta = 1, green = 2, ... }; nil without any equipment.
function ns.OwnGemSignature()
    if not GetInventoryItemLink then return nil end
    local signature, any = {}, false
    local gemOf = (C_Item and C_Item.GetItemGem) or GetItemGem
    for slot = 1, 17 do
        local link = GetInventoryItemLink("player", slot)
        if type(link) == "string" then
            any = true
            for index = 1, 3 do
                local name = gemOf and gemOf(link, index)
                if name then
                    local color = ns.GemColorOf(name)
                    signature[color] = (signature[color] or 0) + 1
                end
            end
        end
    end
    return any and signature or nil
end

--- The filters as ns.Rows wants them.
function ns.Filters()
    local db = ns.Settings()
    return { source = db.source, stats = db.stats, missing = db.missing,
        farmable = db.farmable and (db.content == "mplus" and "dungeon" or "raid") or nil }
end

local function toggle()
    if ns.UI and ns.UI.Toggle then ns.UI.Toggle() end
end

--- /klm opens the window; /klm tooltip switches the line in item tooltips on or off;
--- /klm minimap shows or hides the minimap button.
local function slash(message)
    if (message or ""):lower():match("^%s*minimap%s*$") then
        local db = ns.Settings()
        db.minimapHide = not db.minimapHide
        if ns.RefreshMinimapButton then ns.RefreshMinimapButton() end
        print("|cffd9a24fKeyLootMaster|r minimap button: " .. (db.minimapHide and "hidden" or ("shown - " .. (ns.DescribeMinimapButton and ns.DescribeMinimapButton() or "?"))))
        return
    end
    if (message or ""):lower():match("^%s*tooltip%s*$") then
        local db = ns.Settings()
        db.tooltip = not db.tooltip
        print("|cffd9a24fKeyLootMaster|r tooltip line: " .. (db.tooltip and "on" or "off"))
        return
    end
    toggle()
end

SLASH_KEYLOOTMASTER1 = "/klm"
SLASH_KEYLOOTMASTER2 = "/keylootmaster"
SlashCmdList["KEYLOOTMASTER"] = slash

-- The button in the addon list next to the minimap (the TOC names these functions).
function KeyLootMaster_OnCompartmentClick() toggle() end
function KeyLootMaster_OnCompartmentEnter(_, button)
    if not GameTooltip then return end
    GameTooltip:SetOwner(button, "ANCHOR_LEFT")
    GameTooltip:AddLine("KeyLootMaster", 1, 1, 1)
    GameTooltip:AddLine(L["Left-click opens KeyLootMaster."], 0.8, 0.8, 0.8)
    GameTooltip:Show()
end
function KeyLootMaster_OnCompartmentLeave() if GameTooltip then GameTooltip:Hide() end end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_SPECIALIZATION_CHANGED")
events:RegisterEvent("PLAYER_EQUIPMENT_CHANGED")
events:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then
        ns.Settings()
    elseif event == "PLAYER_SPECIALIZATION_CHANGED" then
        if ns.Tooltip and ns.Tooltip.Invalidate then ns.Tooltip.Invalidate() end
        if ns.UI and ns.UI.Refresh then ns.UI.Refresh() end
    elseif event == "PLAYER_EQUIPMENT_CHANGED" then
        if ns.UI and ns.UI.Refresh then ns.UI.Refresh() end
    end
end)
