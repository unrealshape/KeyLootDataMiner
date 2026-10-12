-- A line in every item tooltip: how many of the best players of your specialization wear it, and where it comes from.
local ADDON, ns = ...

local L = ns.L
local Tooltip = {}
ns.Tooltip = Tooltip

local index, indexFor = nil, nil

--- Drops the cached lookup (the player's specialization changed).
function Tooltip.Invalidate() index, indexFor = nil, nil end

local function shares()
    local id = ns.PlayerSpecId()
    if not id then return nil end
    if index and indexFor == id then return index end
    local class, spec = ns.SpecKeyOf(id)
    index = class and ns.ShareIndex(class, spec) or {}
    indexFor = id
    return index
end

local function addLines(tooltip, data)
    if not ns.Settings().tooltip then return end
    if not (tooltip and tooltip.AddLine and data and data.id) then return end
    local held = shares()
    local share = held and held[data.id]
    if not share then return end
    local parts = {}
    if share.mplus then parts[#parts + 1] = L["Mythic+"] .. " " .. ns.Percent(share.mplus) end
    if share.raid then parts[#parts + 1] = L["Raid"] .. " " .. ns.Percent(share.raid) end
    tooltip:AddLine(" ")
    tooltip:AddLine("|cffd9a24fKeyLootMaster|r  " .. table.concat(parts, "  "))
    local where, more = ns.SourceLabel(data.id)
    if where then
        tooltip:AddLine(where .. (more > 0 and (" (+" .. more .. ")") or ""), 0.7, 0.7, 0.7)
    end
end

if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, addLines)
end

Tooltip.AddLines = addLines
