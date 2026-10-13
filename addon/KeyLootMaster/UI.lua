-- The window: the best items per slot for a specialization, where each drops, and the filters.
local ADDON, ns = ...

local L = ns.L
local UI = {}
ns.UI = UI

local WIDTH, HEIGHT = 840, 580
local ROW_HEIGHT, LIST_TOP, LIST_WIDTH = 30, -112, 500
local ALT_ROWS = 8

local SOURCE_CHOICES = {
    { value = nil, label = "All sources" },
    { value = "dungeon", label = "Dungeon" },
    { value = "raid", label = "Raid" },
    { value = "catalyst", label = "Catalyst / tier" },
    { value = "crafted", label = "Crafted" },
    { value = "other", label = "Other source" },
}
local GROUP_CHOICES = {
    { value = "dungeon", label = "Dungeon players" },
    { value = "all", label = "All top players" },
}
local STAT_NAMES = { c = "Crit", h = "Haste", m = "Mastery", v = "Versatility" }
local SLOT_NAMES = {
    head = "Head", neck = "Neck", shoulder = "Shoulders", back = "Back", chest = "Chest",
    wrist = "Wrists", hands = "Hands", waist = "Waist", legs = "Legs", feet = "Feet",
    finger = "Rings", trinket = "Trinkets", main_hand = "Main hand", off_hand = "Off hand",
}
ns.SLOT_NAMES = SLOT_NAMES

local frame, rows, alternatives, widgets = nil, {}, {}, {}
local page = "items"
local registered = {}
local PAGE_ORDER = { "items", "stats", "gear", "talents", "players" }
local PAGE_LABELS = { items = "Items", stats = "Stats", gear = "Gear", talents = "Talents", players = "Players" }
local stat = { main = {}, minor = {} }
local shownKey, bisSet = nil, {}
local TRACK_NAMES = { veteran = "Veteran", champion = "Champion", hero = "Hero", myth = "Myth" }
local TIER_TEXT = { strong = "Good", option = "Decent" }
local TIER_COLOR = { strong = "ffa335ee", option = "ffffffff" }
local BIS_COLOR = "ffffd100"
local BAR_WIDTH = 44
local SHARE_WIDTH = 78
local MARK_STYLE = {
    must = { text = "Important", color = "ffff8c1a" },
    nice = { text = "Interesting", color = "ff52b7a8" },
}
local selectedSlot = nil
local pending = false

-- ------------------------------------------------------------------ item info

local getItemInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
local getItemIcon = (C_Item and C_Item.GetItemIconByID) or GetItemIcon

local function refreshSoon()
    if pending then return end
    pending = true
    local function run()
        pending = false
        UI.Refresh()
    end
    if C_Timer and C_Timer.After then C_Timer.After(0.2, run) else run() end
end

--- Name and quality of an item; nil until the client has loaded it (a refresh follows).
local function itemNameOf(id)
    local name, _, quality = getItemInfo(id)
    if name then return name, quality end
    if Item and Item.CreateFromItemID then
        Item:CreateFromItemID(id):ContinueOnItemLoad(refreshSoon)
    end
    return nil
end

local function colorFor(quality)
    local color = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[quality or 4]
    if color then return color.r, color.g, color.b end
    return 0.64, 0.21, 0.93
end

local function showItemTooltip(owner, id)
    if not (GameTooltip and id) then return end
    GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
    local db = ns.Settings()
    local lo = ns.DungeonLevel(id, db.content, db.keyLevel, db.vault)
    local link = lo and ns.LinkAtLevel(id, lo)
    if link then GameTooltip:SetHyperlink(link) else GameTooltip:SetItemByID(id) end
    if ns.KeyTable(id) then
        for _, vault in ipairs({ false, true }) do
            GameTooltip:AddLine(" ")
            GameTooltip:AddLine(vault and L["Great Vault"] or L["End of the dungeon"], 1, 0.82, 0)
            for _, group in ipairs(ns.KeyGroups(vault)) do
                GameTooltip:AddDoubleLine(group.label, group.ilvl .. " " .. L[TRACK_NAMES[group.track]] .. " " .. group.rank
                    .. "/" .. ns.TRACK_RANKS, 0.8, 0.8, 0.8, 0.64, 0.21, 0.93)
            end
        end
    end
    if owner.holdText then GameTooltip:AddLine(owner.holdText, 1, 1, 1) end
    GameTooltip:AddLine(L["Right-click marks the item."], 0.6, 0.6, 0.6)
    GameTooltip:Show()
end

local function hideTooltip() if GameTooltip then GameTooltip:Hide() end end

local function sourceText(id)
    local text, more = ns.SourceLabel(id)
    if not text then return L["Other source"] end
    if more > 0 then text = text .. " (+" .. more .. ")" end
    return text
end

-- ------------------------------------------------------------------ small widgets

local function makeText(parent, template)
    return parent:CreateFontString(nil, "OVERLAY", template or "GameFontHighlight")
end

local function makeCheck(parent, label, onClick)
    local check = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
    check:SetSize(24, 24)
    local text = check.Text or check.text
    if text then text:SetText(label) end
    check:SetScript("OnClick", function(self) onClick(self:GetChecked() and true or false) end)
    return check
end

--- A choice from a list: a dropdown, or a button that cycles when the dropdown template is missing.
local function makeChoice(parent, width, options, get, set)
    local ok, dropdown = pcall(CreateFrame, "DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
    if ok and dropdown and dropdown.SetupMenu then
        dropdown:SetWidth(width)
        dropdown:SetupMenu(function(_, root)
            for _, option in ipairs(options) do
                root:CreateRadio(L[option.label], function() return get() == option.value end,
                    function() set(option.value) end)
            end
        end)
        return dropdown, function(label) if dropdown.SetDefaultText then dropdown:SetDefaultText(label) end end
    end
    local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    button:SetSize(width, 24)
    button:SetScript("OnClick", function()
        local at = 1
        for index, option in ipairs(options) do if option.value == get() then at = index end end
        set(options[at % #options + 1].value)
    end)
    return button, function(label) button:SetText(label) end
end

-- ------------------------------------------------------------------ the window

local function specChoices()
    local list = {}
    for _, spec in ipairs(ns.SpecList()) do list[#list + 1] = { value = spec.id, label = spec.label } end
    return list
end

local function buildSpecPicker(parent)
    local ok, dropdown = pcall(CreateFrame, "DropdownButton", nil, parent, "WowStyle1DropdownTemplate")
    if ok and dropdown and dropdown.SetupMenu then
        dropdown:SetWidth(250)
        dropdown:SetupMenu(function(_, root)
            root:CreateRadio(L["Specialization"] .. ": (you)", function() return ns.Settings().spec == nil end,
                function() ns.Settings().spec = nil; UI.Refresh() end)
            local byClass = {}
            for _, spec in ipairs(ns.SpecList()) do
                local menu = byClass[spec.class]
                if not menu then
                    menu = root:CreateButton(ns.Title(spec.class))
                    byClass[spec.class] = menu
                end
                menu:CreateRadio(ns.Title(spec.spec), function() return ns.Settings().spec == spec.id end,
                    function() ns.Settings().spec = spec.id; UI.Refresh() end)
            end
        end)
        return dropdown, function(label) if dropdown.SetDefaultText then dropdown:SetDefaultText(label) end end
    end
    local choices = specChoices()
    table.insert(choices, 1, { value = nil, label = "(you)" })
    local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    button:SetSize(250, 24)
    button:SetScript("OnClick", function()
        local at = 1
        for index, option in ipairs(choices) do if option.value == ns.Settings().spec then at = index end end
        ns.Settings().spec = choices[at % #choices + 1].value
        UI.Refresh()
    end)
    return button, function(label) button:SetText(label) end
end

--- The thin bar under the player count: how large a share of the top players wear the item.
local function addBar(row, right, down)
    row.barBack = row:CreateTexture(nil, "ARTWORK")
    row.barBack:SetSize(BAR_WIDTH, 4)
    row.barBack:SetPoint("RIGHT", row, "RIGHT", right, down)
    row.barBack:SetColorTexture(1, 1, 1, 0.12)
    row.barFill = row:CreateTexture(nil, "OVERLAY")
    row.barFill:SetSize(BAR_WIDTH, 4)
    row.barFill:SetPoint("LEFT", row.barBack, "LEFT", 0, 0)
end

local function hexColor(color)
    return tonumber(color:sub(3, 4), 16) / 255, tonumber(color:sub(5, 6), 16) / 255, tonumber(color:sub(7, 8), 16) / 255
end

-- The color of the n-th stat of a ranking: gold, purple, then white.
local RANK_COLORS = { "ffffd100", "ffa335ee", "ffffffff", "ffffffff" }

--- One line of the stats page: name, bar, value.
local function buildStatRow(parent, top)
    local row = {}
    row.name = makeText(parent, "GameFontHighlight")
    row.name:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, top)
    row.name:SetWidth(150)
    row.name:SetJustifyH("LEFT")
    row.back = parent:CreateTexture(nil, "ARTWORK")
    row.back:SetSize(400, 10)
    row.back:SetPoint("TOPLEFT", parent, "TOPLEFT", 180, top - 3)
    row.back:SetColorTexture(1, 1, 1, 0.1)
    row.fill = parent:CreateTexture(nil, "OVERLAY")
    row.fill:SetSize(400, 10)
    row.fill:SetPoint("LEFT", row.back, "LEFT", 0, 0)
    row.value = makeText(parent, "GameFontHighlight")
    row.value:SetPoint("TOPLEFT", parent, "TOPLEFT", 596, top)
    row.value:SetWidth(210)
    row.value:SetJustifyH("LEFT")
    return row
end

local function showStatRows(rowsOut, ranking)
    local top = 0
    for _, item in ipairs(ranking) do if item.rating > top then top = item.rating end end
    for index, row in ipairs(rowsOut) do
        local item = ranking[index]
        local color = RANK_COLORS[index] or "ffffffff"
        local r, g, b = hexColor(color)
        row.name:SetText("|c" .. color .. L[item.name] .. "|r")
        row.fill:SetColorTexture(r, g, b, 1)
        row.fill:SetWidth(top > 0 and math.max(2, 400 * item.rating / top) or 2)
        row.value:SetText("|c" .. color .. "+" .. item.rating .. "|r   |cff999999" .. string.format("%.1f%%", item.percent) .. "|r")
    end
end

local function rankingText(ranking)
    local parts = {}
    for index, item in ipairs(ranking) do
        parts[index] = "|c" .. (RANK_COLORS[index] or "ffffffff") .. L[item.name]:upper() .. "|r"
    end
    return table.concat(parts, "  >  ")
end

local function buildStatsPanel(parent)
    stat.mainTitle = makeText(parent, "GameFontNormalLarge")
    stat.mainTitle:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -112)
    stat.mainTitle:SetText(L["Optimal secondary stats"])
    for index = 1, #ns.MAIN_STATS do stat.main[index] = buildStatRow(parent, -146 - (index - 1) * 34) end
    stat.mainRank = makeText(parent, "GameFontHighlight")
    stat.mainRank:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -146 - #ns.MAIN_STATS * 34 - 4)
    stat.minorTitle = makeText(parent, "GameFontNormalLarge")
    stat.minorTitle:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -330)
    stat.minorTitle:SetText(L["Additional minor stats"])
    for index = 1, #ns.MINOR_STATS do stat.minor[index] = buildStatRow(parent, -364 - (index - 1) * 34) end
    stat.minorRank = makeText(parent, "GameFontHighlight")
    stat.minorRank:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -364 - #ns.MINOR_STATS * 34 - 4)
    stat.empty = makeText(parent, "GameFontDisable")
    stat.empty:SetPoint("TOPLEFT", parent, "TOPLEFT", 24, -124)
    stat.empty:SetText(L["No stats for this specialization yet."])
end

--- Shows the page that is up and fills it; the item list and its detail column give way to every page but "items".
local function refreshPages(class, spec)
    local statsOn = page == "stats"
    local group = ns.Settings().group
    local data = class and ns.StatsOf(class, spec, group)
    local parts = { stat.mainTitle, stat.mainRank, stat.minorTitle, stat.minorRank }
    for _, list in ipairs({ stat.main, stat.minor }) do
        for _, row in ipairs(list) do
            parts[#parts + 1] = row.name; parts[#parts + 1] = row.back; parts[#parts + 1] = row.fill; parts[#parts + 1] = row.value
        end
    end
    for _, part in ipairs(parts) do part:SetShown(statsOn and data ~= nil) end
    stat.empty:SetShown(statsOn and data == nil)
    widgets.note:SetText("")
    if page ~= "items" then
        for _, row in ipairs(rows) do row:Hide() end
        for _, row in ipairs(alternatives) do row:Hide() end
        widgets.detailTitle:Hide(); widgets.detailSub:Hide(); widgets.altHeader:Hide(); widgets.guide:Hide()
        widgets.message:SetText("")
    else
        for _, row in ipairs(rows) do row:Show() end
        widgets.detailTitle:Show(); widgets.detailSub:Show()
    end
    if statsOn and data then
        local main = ns.StatRanking(data, ns.MAIN_STATS)
        local minor = ns.StatRanking(data, ns.MINOR_STATS)
        showStatRows(stat.main, main)
        showStatRows(stat.minor, minor)
        stat.mainRank:SetText(rankingText(main))
        stat.minorRank:SetText(rankingText(minor))
        widgets.note:SetText(string.format(L["Average of the %d top players"], data.n or 0))
    end
    for name, def in pairs(registered) do
        if page == name then
            widgets.note:SetText(def.refresh(class, spec, group) or "")
        else
            for _, part in ipairs(def.parts or {}) do part:Hide() end
        end
    end
    for _, name in ipairs(PAGE_ORDER) do
        local button = widgets.pageButtons and widgets.pageButtons[name]
        if button then
            if page == name then button:LockHighlight() else button:UnlockHighlight() end
        end
    end
end

--- Pages next to the item list register here (Pages.lua): def.build(frame) returns the parts to hide,
--- def.refresh(class, spec, group) fills them and may return a note for the foot of the window.
function UI.RegisterPage(name, def)
    registered[name] = def
end

local function buildRow(parent, index)
    local row = CreateFrame("Button", nil, parent)
    row:SetSize(LIST_WIDTH, ROW_HEIGHT)
    row:SetPoint("TOPLEFT", parent, "TOPLEFT", 12, LIST_TOP - (index - 1) * ROW_HEIGHT)
    row.highlight = row:CreateTexture(nil, "BACKGROUND")
    row.highlight:SetAllPoints()
    row.highlight:SetColorTexture(1, 1, 1, 0.08)
    row.highlight:Hide()
    row.selected = row:CreateTexture(nil, "BACKGROUND")
    row.selected:SetAllPoints()
    row.selected:SetColorTexture(0.85, 0.64, 0.31, 0.16)
    row.selected:Hide()
    row.slot = makeText(row, "GameFontNormalSmall")
    row.slot:SetPoint("LEFT", 6, 0)
    row.slot:SetWidth(76)
    row.slot:SetJustifyH("LEFT")
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(24, 24)
    row.icon:SetPoint("LEFT", 86, 0)
    row.name = makeText(row, "GameFontHighlight")
    row.name:SetPoint("LEFT", row.icon, "RIGHT", 8, 5)
    row.name:SetWidth(220)
    row.name:SetJustifyH("LEFT")
    row.where = makeText(row, "GameFontDisableSmall")
    row.where:SetPoint("TOPLEFT", row.name, "BOTTOMLEFT", 0, -1)
    row.where:SetWidth(280)
    row.where:SetJustifyH("LEFT")
    row.share = makeText(row, "GameFontHighlight")
    row.share:SetPoint("RIGHT", -8, 5)
    row.share:SetWidth(SHARE_WIDTH)
    row.share:SetJustifyH("RIGHT")
    addBar(row, -8, -8)
    -- the next best item of the slot, small, so the alternative is seen without a click
    row.alt = CreateFrame("Button", nil, row)
    row.alt:SetSize(22, 22)
    row.alt:SetPoint("RIGHT", row, "RIGHT", -(SHARE_WIDTH + 20), 0)
    row.alt.icon = row.alt:CreateTexture(nil, "ARTWORK")
    row.alt.icon:SetAllPoints()
    row.alt:SetScript("OnEnter", function(self) showItemTooltip(self, self.itemId) end)
    row.alt:SetScript("OnLeave", hideTooltip)
    row.alt:SetScript("OnClick", function(self)
        if self.itemId and IsModifiedClick and IsModifiedClick("CHATLINK") then
            local _, link = getItemInfo(self.itemId)
            if link and HandleModifiedItemClick then HandleModifiedItemClick(link) return end
        end
        selectedSlot = row.slotKey
        UI.Refresh()
    end)
    row.alt:Hide()
    row:SetScript("OnEnter", function(self)
        self.highlight:Show()
        showItemTooltip(self, self.itemId)
    end)
    row:SetScript("OnLeave", function(self) self.highlight:Hide(); hideTooltip() end)
    row:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    row:SetScript("OnClick", function(self, button)
        if button == "RightButton" then
            if self.itemId and shownKey then ns.CycleMark(shownKey, self.itemId); UI.Refresh() end
            return
        end
        if self.itemId and IsModifiedClick and IsModifiedClick("CHATLINK") then
            local _, link = getItemInfo(self.itemId)
            if link and HandleModifiedItemClick then HandleModifiedItemClick(link) return end
        end
        selectedSlot = self.slotKey
        UI.Refresh()
    end)
    return row
end

local function buildAlternative(parent, index)
    local row = CreateFrame("Button", nil, parent)
    row:SetSize(280, 36)
    row:SetPoint("TOPLEFT", parent, "TOPLEFT", LIST_WIDTH + 36, -190 - (index - 1) * 38)
    row.icon = row:CreateTexture(nil, "ARTWORK")
    row.icon:SetSize(30, 30)
    row.icon:SetPoint("LEFT", 0, 0)
    row.name = makeText(row, "GameFontHighlight")
    row.name:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 8, -1)
    row.name:SetWidth(160)
    row.name:SetJustifyH("LEFT")
    row.where = makeText(row, "GameFontDisableSmall")
    row.where:SetPoint("TOPLEFT", row.name, "BOTTOMLEFT", 0, -1)
    row.where:SetWidth(160)
    row.where:SetJustifyH("LEFT")
    row.share = makeText(row, "GameFontHighlight")
    row.share:SetPoint("RIGHT", 0, 5)
    row.share:SetWidth(SHARE_WIDTH)
    row.share:SetJustifyH("RIGHT")
    addBar(row, 0, -9)
    row:SetScript("OnEnter", function(self) showItemTooltip(self, self.itemId) end)
    row:SetScript("OnLeave", hideTooltip)
    row:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    row:SetScript("OnClick", function(self, button)
        if button == "RightButton" then
            if self.itemId and shownKey then ns.CycleMark(shownKey, self.itemId); UI.Refresh() end
            return
        end
        if self.itemId and IsModifiedClick and IsModifiedClick("CHATLINK") then
            local _, link = getItemInfo(self.itemId)
            if link and HandleModifiedItemClick then HandleModifiedItemClick(link) end
        end
    end)
    return row
end

--- Opens the Adventure Guide on the boss that drops an item (the first dungeon or raid source).
local function openInGuide(item)
    for _, drop in ipairs(ns.DropsOf(item)) do
        if (drop.kind == "dungeon" or drop.kind == "raid") and drop.instance ~= 0 then
            if C_AddOns and C_AddOns.LoadAddOn then C_AddOns.LoadAddOn("Blizzard_EncounterJournal") end
            if EncounterJournal_OpenJournal then
                pcall(EncounterJournal_OpenJournal, nil, drop.instance, drop.encounter, nil, nil, item)
            end
            return
        end
    end
end

local function build()
    frame = CreateFrame("Frame", "KeyLootMasterFrame", UIParent, "BasicFrameTemplateWithInset")
    frame:SetSize(WIDTH, HEIGHT)
    frame:SetPoint("CENTER")
    frame:SetFrameStrata("HIGH")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:SetClampedToScreen(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", function(self) self:StartMoving() end)
    frame:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
    frame:Hide()
    if UISpecialFrames then table.insert(UISpecialFrames, "KeyLootMasterFrame") end

    local title = frame.TitleText or makeText(frame, "GameFontNormal")
    if not frame.TitleText then title:SetPoint("TOP", 0, -6) end
    title:SetText("KeyLootMaster")

    widgets.spec, widgets.setSpecText = buildSpecPicker(frame)
    widgets.spec:SetPoint("TOPLEFT", 14, -34)

    widgets.mplus = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    widgets.mplus:SetSize(90, 24)
    widgets.mplus:SetPoint("LEFT", widgets.spec, "RIGHT", 16, 0)
    widgets.mplus:SetText(L["Mythic+"])
    widgets.mplus:SetScript("OnClick", function() ns.Settings().content = "mplus"; UI.Refresh() end)
    widgets.raid = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    widgets.raid:SetSize(90, 24)
    widgets.raid:SetPoint("LEFT", widgets.mplus, "RIGHT", 4, 0)
    widgets.raid:SetText(L["Raid"])
    widgets.raid:SetScript("OnClick", function() ns.Settings().content = "raid"; UI.Refresh() end)

    local keyChoices = {}
    for _, level in ipairs(ns.KEY_LEVELS) do keyChoices[#keyChoices + 1] = { value = level, label = ns.KeyLabel(level) } end
    widgets.key, widgets.setKeyText = makeChoice(frame, 110, keyChoices,
        function() return ns.Settings().keyLevel end,
        function(value) ns.Settings().keyLevel = value; UI.Refresh() end)
    widgets.key:SetPoint("LEFT", widgets.raid, "RIGHT", 16, 0)
    widgets.vault = makeCheck(frame, L["Great Vault"], function(on) ns.Settings().vault = on; UI.Refresh() end)
    widgets.vault:SetPoint("LEFT", widgets.key, "RIGHT", 6, 0)

    widgets.stamp = makeText(frame, "GameFontDisableSmall")
    widgets.stamp:SetPoint("TOPRIGHT", -16, -40)

    widgets.source, widgets.setSourceText = makeChoice(frame, 170, SOURCE_CHOICES,
        function() return ns.Settings().source end,
        function(value) ns.Settings().source = value; UI.Refresh() end)
    widgets.source:SetPoint("TOPLEFT", 14, -68)

    widgets.stats = {}
    local previous = widgets.source
    for _, pair in ipairs(ns.STATS) do
        local letter = pair[1]
        local check = makeCheck(frame, L[STAT_NAMES[letter]], function(on)
            local db, kept = ns.Settings(), {}
            for _, other in ipairs(ns.STATS) do
                local has = db.stats:find(other[1], 1, true) ~= nil
                if other[1] == letter then has = on end
                if has then kept[#kept + 1] = other[1] end
            end
            db.stats = table.concat(kept)
            UI.Refresh()
        end)
        check:SetPoint("LEFT", previous, "RIGHT", previous == widgets.source and 16 or 70, 0)
        widgets.stats[letter] = check
        previous = check
    end
    widgets.missing = makeCheck(frame, L["Only missing"], function(on) ns.Settings().missing = on; UI.Refresh() end)
    widgets.missing:SetPoint("LEFT", previous, "RIGHT", 84, 0)

    widgets.farmable = makeCheck(frame, L["Only farmable here"], function(on) ns.Settings().farmable = on; UI.Refresh() end)
    widgets.farmable:SetPoint("LEFT", widgets.missing, "RIGHT", 96, 0)
    widgets.group, widgets.setGroupText = makeChoice(frame, 118, GROUP_CHOICES,
        function() return ns.Settings().group end,
        function(value) ns.Settings().group = value; UI.Refresh() end)
    widgets.group:SetPoint("LEFT", widgets.farmable, "RIGHT", 96, 0)

    for index = 1, #ns.SLOT_ORDER do rows[index] = buildRow(frame, index) end

    widgets.detailTitle = makeText(frame, "GameFontNormalLarge")
    widgets.detailTitle:SetPoint("TOPLEFT", frame, "TOPLEFT", LIST_WIDTH + 36, -112)
    widgets.detailSub = makeText(frame, "GameFontDisableSmall")
    widgets.detailSub:SetPoint("TOPLEFT", widgets.detailTitle, "BOTTOMLEFT", 0, -4)
    widgets.detailSub:SetWidth(280)
    widgets.detailSub:SetJustifyH("LEFT")
    widgets.altHeader = makeText(frame, "GameFontNormalSmall")
    widgets.altHeader:SetPoint("TOPLEFT", frame, "TOPLEFT", LIST_WIDTH + 36, -170)
    widgets.altHeader:SetText(L["Alternatives"])
    for index = 1, ALT_ROWS do alternatives[index] = buildAlternative(frame, index) end

    widgets.guide = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    widgets.guide:SetSize(200, 24)
    widgets.guide:SetPoint("BOTTOMRIGHT", -20, 18)
    widgets.guide:SetText(L["Open the Adventure Guide"])
    widgets.guide:SetScript("OnClick", function(self) if self.itemId then openInGuide(self.itemId) end end)

    widgets.message = makeText(frame, "GameFontDisable")
    widgets.message:SetPoint("TOPLEFT", frame, "TOPLEFT", 24, LIST_TOP - 12)
    widgets.message:SetWidth(LIST_WIDTH - 20)
    widgets.message:SetJustifyH("LEFT")

    buildStatsPanel(frame)
    widgets.note = makeText(frame, "GameFontDisableSmall")
    widgets.note:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 24, 52)
    for _, def in pairs(registered) do def.parts = def.build(frame) end
    widgets.pageButtons = {}
    for index, name in ipairs(PAGE_ORDER) do
        local button = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        button:SetSize(92, 24)
        button:SetPoint("BOTTOMLEFT", 20 + (index - 1) * 96, 18)
        button:SetText(L[PAGE_LABELS[name]])
        button:SetScript("OnClick", function() page = name; UI.Refresh() end)
        widgets.pageButtons[name] = button
    end
end

-- ------------------------------------------------------------------ refresh

--- "42 of 50 top players (84%)": how many of the players of the shown group wear the item.
local function holdTextOf(entry)
    local db = ns.Settings()
    local format = (db.content == "mplus" and db.group == "dungeon") and L["%d of %d dungeon players (%s)"]
        or L["%d of %d top players (%s)"]
    return string.format(format, math.floor(entry.share * entry.sample + 0.5), entry.sample, ns.Percent(entry.share))
end

--- "292 Champion  +13" for an item that drops at a key level; the difference to what is worn.
local function levelText(id, slotKey)
    local db = ns.Settings()
    local ilvl, track, rank = ns.DungeonLevel(id, db.content, db.keyLevel, db.vault)
    if not ilvl then return nil end
    local text = "|cffa335ee" .. ilvl .. " " .. L[TRACK_NAMES[track]] .. " " .. rank .. "/" .. ns.TRACK_RANKS .. "|r"
    local have = ns.WornItemLevel(slotKey)
    if have > 0 then
        local diff = ilvl - have
        if diff > 0 then text = text .. "  |cff52e052+" .. diff .. "|r"
        elseif diff < 0 then text = text .. "  |cffe05252" .. diff .. "|r"
        else text = text .. "  |cff999999=|r" end
    end
    return text
end

--- The BiS or tier tag and the player's own mark behind an item name.
local function tagsOf(id, share)
    local text = ""
    if bisSet[id] then
        text = text .. "  |cffffd100[" .. L["BiS"] .. "]|r"
    else
        local tier = share and ns.TierOf(share)
        if tier then text = text .. "  |c" .. TIER_COLOR[tier] .. "[" .. L[TIER_TEXT[tier]] .. "]|r" end
    end
    local mark = shownKey and ns.MarkOf(shownKey, id)
    local style = mark and MARK_STYLE[mark]
    if style then text = text .. "  |c" .. style.color .. "* " .. L[style.text] .. "|r" end
    return text
end

local function fillItem(target, entry, worn, slotKey)
    local id = entry.item
    target.itemId = id
    target.icon:SetTexture(getItemIcon(id))
    local name, quality = itemNameOf(id)
    local levelLine = levelText(id, slotKey)
    local r, g, b = colorFor(levelLine and 4 or quality)
    target.name:SetTextColor(r, g, b)
    target.name:SetText((name or ("[" .. id .. "]")) .. (worn[id] and ("  |cff52b7a8" .. L["Equipped"] .. "|r") or "") .. tagsOf(id, entry.share))
    target.where:SetText(levelLine and (levelLine .. "   " .. sourceText(id)) or sourceText(id))
    local count = math.floor(entry.share * entry.sample + 0.5)
    local color = bisSet[id] and BIS_COLOR or (ns.TierOf(entry.share) and TIER_COLOR[ns.TierOf(entry.share)]) or "ffffffff"
    target.share:SetText("|c" .. color .. count .. "|r |cff999999" .. ns.Percent(entry.share) .. "|r")
    local red, green, blue = tonumber(color:sub(3, 4), 16) / 255, tonumber(color:sub(5, 6), 16) / 255, tonumber(color:sub(7, 8), 16) / 255
    target.barFill:SetColorTexture(red, green, blue, 1)
    target.barFill:SetWidth(math.max(2, BAR_WIDTH * entry.share))
    target.barBack:Show(); target.barFill:Show()
    target.holdText = holdTextOf(entry)
end

function UI.Refresh()
    if not frame or not frame:IsShown() then return end
    local _, class, spec = ns.ShownSpec()
    if class then ns.UseProfile(class .. "-" .. spec) end
    local db = ns.Settings()
    local worn = ns.EquippedItems()
    shownKey = class and (class .. "-" .. spec) or nil
    local contentKey = ns.ContentKey(class or "", spec or "", db.content, db.group)
    bisSet = ns.BisItems(class or "", spec or "", contentKey)
    local data = ns.Rows(class or "", spec or "", contentKey, ns.Filters(), db.missing and worn or nil)

    widgets.setSpecText(class and (ns.Title(class) .. " - " .. ns.Title(spec) .. (db.spec and "" or "  (you)"))
        or L["No data for this specialization."])
    if db.content == "mplus" then
        widgets.mplus:LockHighlight(); widgets.raid:UnlockHighlight()
    else
        widgets.raid:LockHighlight(); widgets.mplus:UnlockHighlight()
    end
    widgets.key:SetShown(db.content == "mplus")
    widgets.vault:SetShown(db.content == "mplus")
    widgets.vault:SetChecked(db.vault)
    widgets.setKeyText(L["Key level"] .. ": " .. ns.KeyLabel(db.keyLevel))
    for _, choice in ipairs(SOURCE_CHOICES) do
        if choice.value == db.source then widgets.setSourceText(L[choice.label]) end
    end
    for letter, check in pairs(widgets.stats) do check:SetChecked(db.stats:find(letter, 1, true) ~= nil) end
    widgets.missing:SetChecked(db.missing)
    widgets.farmable:SetChecked(db.farmable)
    local groups = class and db.content == "mplus" and ns.HasGroups(class, spec)
    widgets.group:SetShown(groups and true or false)
    for _, choice in ipairs(GROUP_CHOICES) do
        if choice.value == db.group then widgets.setGroupText(L[choice.label]) end
    end
    widgets.stamp:SetText(KeyLootMasterMeta and (L["Data of"] .. " " .. KeyLootMasterMeta.generated:sub(1, 10)) or "")

    local any, firstWithItems = false, nil
    for index, row in ipairs(rows) do
        local entry = data[index]
        row.slotKey = entry.slot
        row.slot:SetText(L[SLOT_NAMES[entry.slot]])
        local top = entry.items[1]
        if top then
            any = true
            firstWithItems = firstWithItems or entry.slot
            row.icon:Show(); row.where:Show(); row.share:Show()
            fillItem(row, top, worn, entry.slot)
            local second = entry.items[2]
            if second then
                row.alt.itemId = second.item
                row.alt.icon:SetTexture(getItemIcon(second.item))
                row.alt.holdText = holdTextOf(second)
                row.alt:Show()
            else
                row.alt.itemId = nil
                row.alt:Hide()
            end
        else
            row.itemId = nil
            row.icon:Hide(); row.where:Hide(); row.share:Hide(); row.barBack:Hide(); row.barFill:Hide(); row.alt.itemId = nil; row.alt:Hide()
            row.name:SetTextColor(0.5, 0.5, 0.5)
            row.name:SetText("-")
        end
    end
    -- Keep the selected slot when it still has items, else the first slot that has some.
    local stillValid = false
    for _, entry in ipairs(data) do
        if entry.slot == selectedSlot and entry.items[1] then stillValid = true end
    end
    if not stillValid then selectedSlot = firstWithItems end
    for index, row in ipairs(rows) do
        if data[index].slot == selectedSlot then row.selected:Show() else row.selected:Hide() end
    end
    widgets.message:SetText(not class and L["No data for this specialization."]
        or (not any and L["Nothing matches the filters."]) or "")

    local selected
    for _, entry in ipairs(data) do if entry.slot == selectedSlot then selected = entry end end
    widgets.guide.itemId = nil
    if selected and selected.items[1] then
        local top = selected.items[1]
        widgets.detailTitle:SetText(L[SLOT_NAMES[selected.slot]])
        local facts = ns.StatText((ns.FactsOf(top.item)), {
            c = L["Crit"], h = L["Haste"], m = L["Mastery"], v = L["Versatility"] })
        widgets.detailSub:SetText(string.format(L["of %d players"], top.sample)
            .. ((facts ~= "") and ("  -  " .. facts) or ""))
        widgets.guide.itemId = top.item
        local kinds = ns.KindsOf(top.item)
        widgets.guide:SetShown(kinds.dungeon or kinds.raid or false)
        for index, row in ipairs(alternatives) do
            local entry = selected.items[index + 1]
            if entry then
                row:Show()
                fillItem(row, entry, worn, selected.slot)
            else
                row.itemId = nil
                row:Hide()
            end
        end
        widgets.altHeader:SetShown(#selected.items > 1)
    else
        widgets.detailTitle:SetText("")
        widgets.detailSub:SetText("")
        widgets.altHeader:Hide()
        widgets.guide:Hide()
        for _, row in ipairs(alternatives) do
            row.itemId = nil
            row:Hide()
        end
    end
    refreshPages(class, spec)
end

--- Shows one of the pages ("items", "stats", "gear", "talents", "players").
function UI.SetPage(name)
    page = name
    UI.Refresh()
end

function UI.Toggle()
    if not frame then build() end
    if frame:IsShown() then
        frame:Hide()
    else
        frame:Show()
        UI.Refresh()
    end
end
