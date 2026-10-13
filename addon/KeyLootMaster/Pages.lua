-- The pages next to the item list: enchantments and gems, talents, the best players.
-- Every page reads KeyLootMasterGear[class][spec][group] (Data/Gear.lua, made by the pipeline).
local _, ns = ...

local L = ns.L
local UI = ns.UI

local GOLD, WHITE, GREY, GREEN, RED = "ffffd100", "ffffffff", "ff999999", "ff52e052", "ffe05252"
local GEM_COLORS = {
    red = "ffff5050", green = "ff50d050", purple = "ffb060ff", blue = "ff5aa0ff", meta = GOLD, other = WHITE,
}
local MAX_SLOT_ROWS = 14
local TOP_PLAYERS = 10

local function paint(color, text) return "|c" .. color .. text .. "|r" end

local function makeText(parent, template, x, y, width, justify)
    local text = parent:CreateFontString(nil, "OVERLAY", template or "GameFontHighlight")
    text:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    if width then text:SetWidth(width) end
    text:SetJustifyH(justify or "LEFT")
    return text
end

--- Shaded by how many of the group chose it: gold from 80 %, white from 30 %, grey below.
local function shareColor(count, total)
    local share = total > 0 and count / total or 0
    if share >= 0.8 then return GOLD end
    if share >= 0.3 then return WHITE end
    return GREY
end

-- ------------------------------------------------------------------ the copy box for an import string

local copyBox

--- Shows an import string in a small window with the text selected: Ctrl+C, then paste it into the
--- import window of the talent frame.
local function showCopyBox(code)
    if not copyBox then
        copyBox = CreateFrame("Frame", "KeyLootMasterCopyBox", UIParent, "BasicFrameTemplateWithInset")
        copyBox:SetSize(520, 120)
        copyBox:SetPoint("CENTER", 0, 120)
        copyBox:SetFrameStrata("DIALOG")
        copyBox:EnableMouse(true)
        copyBox.hint = copyBox:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        copyBox.hint:SetPoint("TOPLEFT", 16, -34)
        copyBox.hint:SetWidth(488)
        copyBox.hint:SetJustifyH("LEFT")
        copyBox.hint:SetText(L["Press Ctrl+C, then paste it into the talent import window."])
        copyBox.edit = CreateFrame("EditBox", nil, copyBox, "InputBoxTemplate")
        copyBox.edit:SetSize(480, 24)
        copyBox.edit:SetPoint("TOPLEFT", 20, -72)
        copyBox.edit:SetAutoFocus(true)
        copyBox.edit:SetScript("OnEscapePressed", function() copyBox:Hide() end)
        if UISpecialFrames then table.insert(UISpecialFrames, "KeyLootMasterCopyBox") end
    end
    copyBox.edit:SetText(code)
    copyBox:Show()
    copyBox.edit:SetFocus()
    copyBox.edit:HighlightText()
end

-- ------------------------------------------------------------------ gear page

local gear = { rows = {}, gems = {}, sets = {}, embellishments = {} }

local function buildGear(parent)
    local parts = {}
    local function keep(part) parts[#parts + 1] = part; return part end
    gear.enchantTitle = keep(makeText(parent, "GameFontNormalLarge", 24, -112))
    gear.enchantTitle:SetText(L["Enchantments"])
    for index = 1, MAX_SLOT_ROWS do
        local row = keep(CreateFrame("Button", nil, parent))
        row:SetSize(420, 24)
        row:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -142 - (index - 1) * 26)
        row.slot = makeText(row, "GameFontNormalSmall", 0, -6, 80)
        row.name = makeText(row, "GameFontHighlight", 84, -4, 250)
        row.count = makeText(row, "GameFontHighlight", 336, -4, 80, "RIGHT")
        row:SetScript("OnEnter", function(self)
            if not (GameTooltip and self.options) then return end
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:AddLine(L[ns.SLOT_NAMES[self.slotKey]], 1, 0.82, 0)
            for _, option in ipairs(self.options) do
                GameTooltip:AddDoubleLine(option.name, option.n .. "/" .. (self.total or 0), 1, 1, 1, 0.8, 0.8, 0.8)
            end
            GameTooltip:Show()
        end)
        row:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
        gear.rows[index] = row
    end
    gear.gemTitle = keep(makeText(parent, "GameFontNormalLarge", 480, -112))
    gear.gemTitle:SetText(L["Gems"])
    for index = 1, 6 do gear.gems[index] = keep(makeText(parent, "GameFontHighlight", 480, -142 - (index - 1) * 22, 330)) end
    gear.setTitle = keep(makeText(parent, "GameFontNormalLarge", 480, -290))
    gear.setTitle:SetText(L["Gem sets"])
    for index = 1, 3 do gear.sets[index] = keep(makeText(parent, "GameFontHighlight", 480, -320 - (index - 1) * 22, 330)) end
    gear.own = keep(makeText(parent, "GameFontHighlight", 480, -392, 330))
    gear.embTitle = keep(makeText(parent, "GameFontNormalLarge", 480, -430))
    gear.embTitle:SetText(L["Embellishments"])
    for index = 1, 3 do gear.embellishments[index] = keep(makeText(parent, "GameFontHighlight", 480, -460 - (index - 1) * 22, 330)) end
    gear.empty = keep(makeText(parent, "GameFontDisable", 24, -124, 600))
    gear.empty:SetText(L["No gear data for this specialization yet."])
    return parts
end

local function refreshGear(class, spec, group)
    local info = class and ns.GearInfo(class, spec, group)
    gear.empty:SetShown(info == nil)
    for _, part in ipairs({ gear.enchantTitle, gear.gemTitle, gear.setTitle, gear.own, gear.embTitle }) do part:SetShown(info ~= nil) end
    for _, list in ipairs({ gear.gems, gear.sets, gear.embellishments }) do
        for _, text in ipairs(list) do text:SetShown(info ~= nil) end
    end
    if not info then
        for _, row in ipairs(gear.rows) do row:Hide() end
        return nil
    end
    local total = info.n or 0
    local used = 0
    for _, slot in ipairs(ns.SLOT_ORDER) do
        local options = info.enchants and info.enchants[slot]
        if options and options[1] and used < MAX_SLOT_ROWS then
            used = used + 1
            local row = gear.rows[used]
            local top = options[1]
            row.slotKey, row.options, row.total = slot, options, total
            row.slot:SetText(L[ns.SLOT_NAMES[slot]])
            row.name:SetText(top.name)
            local mine = ns.OwnEnchantId(slot)
            local mark = ""
            if mine ~= nil then
                mark = (mine == top.id) and ("  " .. paint(GREEN, "OK")) or ("  " .. paint(RED, "!"))
            end
            row.count:SetText(paint(shareColor(top.n, total), top.n .. "/" .. total) .. mark)
            row:Show()
        end
    end
    for index = used + 1, MAX_SLOT_ROWS do gear.rows[index]:Hide() end
    for index, text in ipairs(gear.gems) do
        local gem = info.gems and info.gems[index]
        text:SetText(gem and (paint(GEM_COLORS[gem.color] or WHITE, gem.name) .. "   " .. paint(GREY, gem.n)) or "")
    end
    for index, text in ipairs(gear.sets) do
        local set = info.gemSets and info.gemSets[index]
        text:SetText(set and (paint(shareColor(set.n, total), set.n .. "x") .. "   " .. ns.SigText(set.sig, L)) or "")
    end
    local top = info.gemSets and info.gemSets[1]
    local own = ns.OwnGemSignature()
    if top and own then
        local difference = ns.SigDiff(own, top.sig, L)
        gear.own:SetText(paint(GREY, L["You"] .. ": ") .. ns.SigText(own, L) ..
            (difference == "" and ("   " .. paint(GREEN, "OK")) or ("   " .. paint(RED, difference))))
    else
        gear.own:SetText("")
    end
    for index, text in ipairs(gear.embellishments) do
        local item = info.embellishments and info.embellishments[index]
        text:SetText(item and (item.name .. "   " .. paint(GREY, item.n)) or "")
    end
    return string.format(L["Average of the %d top players"], total)
end

-- ------------------------------------------------------------------ talents page

local talents = { builds = {}, columns = {} }
local COLUMN_TITLES = { "Class talents", "Specialization talents", "Hero talents" }

local function buildTalents(parent)
    local parts = {}
    local function keep(part) parts[#parts + 1] = part; return part end
    talents.title = keep(makeText(parent, "GameFontNormalLarge", 24, -112))
    talents.title:SetText(L["Builds"])
    for index = 1, 3 do
        local row = keep(CreateFrame("Frame", nil, parent))
        row:SetSize(780, 48)
        row:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -142 - (index - 1) * 52)
        row.bg = row:CreateTexture(nil, "BACKGROUND")
        row.bg:SetAllPoints()
        row.bg:SetColorTexture(1, 1, 1, 0.05)
        row.head = makeText(row, "GameFontHighlight", 8, -6, 600)
        row.code = makeText(row, "GameFontDisableSmall", 8, -26, 640)
        row.copy = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
        row.copy:SetSize(110, 24)
        row.copy:SetPoint("TOPRIGHT", row, "TOPRIGHT", -8, -12)
        row.copy:SetText(L["Copy build"])
        row.copy:SetScript("OnClick", function() if row.build then showCopyBox(row.build.code) end end)
        talents.builds[index] = row
    end
    talents.heroes = keep(makeText(parent, "GameFontHighlight", 24, -302, 780))
    for index = 1, #COLUMN_TITLES do
        talents.columns[index] = keep(makeText(parent, "GameFontHighlightSmall", 24 + (index - 1) * 266, -334, 256))
    end
    talents.empty = keep(makeText(parent, "GameFontDisable", 24, -124, 600))
    talents.empty:SetText(L["No talent data for this specialization yet."])
    return parts
end

local function refreshTalents(class, spec, group)
    local info = class and ns.GearInfo(class, spec, group)
    local has = info ~= nil and ((info.builds and info.builds[1]) or (info.talents and info.talents[1])) ~= nil
    talents.empty:SetShown(not has)
    talents.title:SetShown(has)
    talents.heroes:SetShown(has)
    for _, column in ipairs(talents.columns) do column:SetShown(has) end
    if not has then
        for _, row in ipairs(talents.builds) do row:Hide() end
        return nil
    end
    local total = info.n or 0
    for index, row in ipairs(talents.builds) do
        local build = info.builds and info.builds[index]
        row.build = build
        if build then
            row:Show()
            row.head:SetText(paint(index == 1 and GOLD or WHITE, L["Build"] .. " " .. index) ..
                (build.hero and ("   " .. build.hero) or "") .. "   " .. paint(GREY, string.format(L["%d players"], build.n)))
            row.code:SetText(build.code:sub(1, 90) .. (#build.code > 90 and "..." or ""))
        else
            row:Hide()
        end
    end
    local heroes = {}
    for _, hero in ipairs(info.heroes or {}) do heroes[#heroes + 1] = hero.name .. " " .. paint(GREY, hero.n) end
    talents.heroes:SetText(#heroes > 0 and (paint(GOLD, L["Hero talents"] .. ": ") .. table.concat(heroes, "   ")) or "")
    local byTree = { class = {}, spec = {}, hero = {} }
    for _, talent in ipairs(info.talents or {}) do
        local list = byTree[talent.tree]
        if list then list[#list + 1] = talent end
    end
    for index, tree in ipairs({ "class", "spec", "hero" }) do
        local lines = { paint(GOLD, L[COLUMN_TITLES[index]]) }
        for position, talent in ipairs(byTree[tree]) do
            if position > 12 then break end
            lines[#lines + 1] = paint(shareColor(talent.n, total), talent.name) .. "  " .. paint(GREY, talent.n)
        end
        talents.columns[index]:SetText(table.concat(lines, "\n"))
    end
    return string.format(L["Average of the %d top players"], total)
end

-- ------------------------------------------------------------------ players page

local players = { rows = {} }

local function buildPlayers(parent)
    local parts = {}
    local function keep(part) parts[#parts + 1] = part; return part end
    players.title = keep(makeText(parent, "GameFontNormalLarge", 24, -112))
    players.title:SetText(L["Best players"])
    for index = 1, TOP_PLAYERS do
        local y = -146 - (index - 1) * 30
        players.rows[index] = {
            rank = keep(makeText(parent, "GameFontNormal", 24, y, 30)),
            name = keep(makeText(parent, "GameFontHighlight", 60, y, 200)),
            realm = keep(makeText(parent, "GameFontDisable", 270, y, 190)),
            race = keep(makeText(parent, "GameFontHighlight", 470, y, 110)),
            ilvl = keep(makeText(parent, "GameFontHighlight", 590, y, 60)),
            rating = keep(makeText(parent, "GameFontHighlight", 660, y, 80)),
        }
    end
    players.empty = keep(makeText(parent, "GameFontDisable", 24, -124, 600))
    players.empty:SetText(L["No player data for this specialization yet."])
    return parts
end

local function refreshPlayers(class, spec, group)
    local info = class and ns.GearInfo(class, spec, group)
    local list = info and info.players or {}
    players.empty:SetShown(#list == 0)
    players.title:SetShown(#list > 0)
    for index, row in ipairs(players.rows) do
        local player = list[index]
        for _, field in pairs(row) do field:SetShown(player ~= nil) end
        if player then
            row.rank:SetText(index)
            row.name:SetText(player.name)
            row.realm:SetText((player.realm or "") .. (player.region and (" (" .. player.region:upper() .. ")") or ""))
            row.race:SetText(player.race or "")
            row.ilvl:SetText(player.ilvl and (player.ilvl .. " ilvl") or "")
            row.rating:SetText(paint(GOLD, player.rating or (player.key and ("+" .. player.key)) or ""))
        end
    end
    return nil
end

UI.RegisterPage("gear", { build = buildGear, refresh = refreshGear })
UI.RegisterPage("talents", { build = buildTalents, refresh = refreshTalents })
UI.RegisterPage("players", { build = buildPlayers, refresh = refreshPlayers })
