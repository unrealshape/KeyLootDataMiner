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
}
ns.DEFAULTS = DEFAULTS

--- The saved settings with the defaults filled in.
function ns.Settings()
    local db = KeyLootMasterDB
    for key, value in pairs(DEFAULTS) do
        if db[key] == nil then db[key] = value end
    end
    if db.content ~= "mplus" and db.content ~= "raid" then db.content = "mplus" end
    return db
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

--- The filters as ns.Rows wants them.
function ns.Filters()
    local db = ns.Settings()
    return { source = db.source, stats = db.stats, missing = db.missing }
end

local function toggle()
    if ns.UI and ns.UI.Toggle then ns.UI.Toggle() end
end

--- /klm opens the window; /klm tooltip switches the line in item tooltips on or off.
local function slash(message)
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
