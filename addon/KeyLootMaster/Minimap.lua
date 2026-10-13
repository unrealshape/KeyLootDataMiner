-- The button on the minimap: click opens the window, dragging moves it around the rim.
local _, ns = ...

local L = ns.L

local ICON = "Interface/Icons/inv_cullingofstratholme_keystone"
local RADIUS = 80

local button

local function place(angle)
    local radians = math.rad(angle)
    button:ClearAllPoints()
    button:SetPoint("CENTER", Minimap, "CENTER", math.cos(radians) * RADIUS, math.sin(radians) * RADIUS)
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
    button = CreateFrame("Button", "KeyLootMasterMinimapButton", Minimap)
    button:SetSize(31, 31)
    button:SetFrameStrata("MEDIUM")
    button:SetFrameLevel(8)
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

--- Shows or hides the button as the saved setting says, creating it on first use.
function ns.RefreshMinimapButton()
    local db = ns.Settings()
    if db.minimapHide then
        if button then button:Hide() end
        return
    end
    if not button then create() end
    place(db.minimapAngle)
    button:Show()
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", ns.RefreshMinimapButton)
