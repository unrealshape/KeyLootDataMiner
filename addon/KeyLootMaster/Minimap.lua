-- The button on the minimap: click opens the window, dragging moves it around the rim.
--
-- It hangs on UIParent and is only anchored to the minimap. A frame parented to the minimap is
-- picked up by minimap-button collectors (EllesmereUI's flyout, ElvUI's button bar) and hidden from
-- the map; one parented elsewhere is left where it is.
local _, ns = ...

local L = ns.L

local ICON = "Interface/Icons/inv_cullingofstratholme_keystone"
local MARGIN = 6

local button

--- How far from the center of the minimap the button sits, in units of the button's own scale.
local function radius()
    local width = tonumber(Minimap:GetWidth()) or 140
    local mapScale = tonumber(Minimap:GetEffectiveScale()) or 1
    local ownScale = tonumber(UIParent:GetEffectiveScale()) or 1
    return width / 2 * (mapScale / ownScale) + MARGIN
end

local function place(angle)
    local radians = math.rad(angle)
    local distance = radius()
    button:ClearAllPoints()
    button:SetPoint("CENTER", Minimap, "CENTER", math.cos(radians) * distance, math.sin(radians) * distance)
end

local function drag()
    local scale = Minimap:GetEffectiveScale()
    local mx, my = Minimap:GetCenter()
    local cx, cy = GetCursorPosition()
    local angle = math.deg(math.atan2(cy / scale - my, cx / scale - mx))
    ns.Settings().minimapAngle = angle
    place(angle)
end

local function create()
    button = CreateFrame("Button", "KeyLootMasterMinimapButton", UIParent)
    button:SetSize(31, 31)
    button:SetFrameStrata("MEDIUM")
    button:SetFrameLevel(20)
    button:SetClampedToScreen(true)
    button:RegisterForClicks("LeftButtonUp")
    button:RegisterForDrag("LeftButton")
    button:SetHighlightTexture("Interface/Minimap/UI-Minimap-ZoomButton-Highlight")

    local icon = button:CreateTexture(nil, "ARTWORK")
    icon:SetSize(20, 20)
    icon:SetPoint("CENTER", button, "CENTER", 0, 1)
    icon:SetTexture(ICON)

    local border = button:CreateTexture(nil, "OVERLAY")
    border:SetSize(53, 53)
    border:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)
    border:SetTexture("Interface/Minimap/MiniMap-TrackingBorder")

    button:SetScript("OnClick", function() if ns.UI and ns.UI.Toggle then ns.UI.Toggle() end end)
    button:SetScript("OnDragStart", function(self) self:SetScript("OnUpdate", drag) end)
    button:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
    button:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_LEFT")
        GameTooltip:AddLine("KeyLootMaster", 1, 1, 1)
        GameTooltip:AddLine(L["Left-click opens KeyLootMaster."], 0.8, 0.8, 0.8)
        GameTooltip:AddLine(L["Drag to move the button."], 0.8, 0.8, 0.8)
        GameTooltip:Show()
    end)
    button:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

local function say(text) print("|cffd9a24fKeyLootMaster|r " .. text) end

--- Shows or hides the button as the saved setting says, creating it on first use. A failure is
--- said in the chat instead of leaving the minimap empty without a word.
function ns.RefreshMinimapButton()
    local db = ns.Settings()
    if db.minimapHide then
        if button then button:Hide() end
        return
    end
    if not button then
        local ok, failure = pcall(create)
        if not ok then
            button = nil
            say("minimap button could not be created: " .. tostring(failure))
            return
        end
    end
    place(db.minimapAngle)
    button:Show()
end

--- What /klm minimap says: whether the button exists, where it sits and how big its parent is.
function ns.DescribeMinimapButton()
    if not button then return "no button" end
    local point, _, _, x, y = button:GetPoint()
    return string.format("%s, %s %.0f/%.0f, minimap %.0fx%.0f, strata %s", button:IsShown() and "shown" or "hidden",
        tostring(point), tonumber(x) or 0, tonumber(y) or 0, tonumber(Minimap:GetWidth()) or 0,
        tonumber(Minimap:GetHeight()) or 0, tostring(button:GetFrameStrata()))
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function() ns.RefreshMinimapButton() end)
