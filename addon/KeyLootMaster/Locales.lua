-- Texts. English is the key; other languages override it, a missing text shows the English one.
local _, ns = ...

local L = setmetatable({}, { __index = function(_, key) return key end })
ns.L = L

local overrides = {
    deDE = {
        ["Mythic+"] = "Mythic+",
        ["Raid"] = "Raid",
        ["Only missing"] = "Nur fehlende",
        ["Source"] = "Quelle",
        ["All sources"] = "Alle Quellen",
        ["Dungeon"] = "Dungeon",
        ["Catalyst / tier"] = "Katalysator / Tier",
        ["Crafted"] = "Hergestellt",
        ["Vendor"] = "Händler",
        ["Other source"] = "Andere Quelle",
        ["Crit"] = "Krit",
        ["Haste"] = "Tempo",
        ["Mastery"] = "Meisterschaft",
        ["Versatility"] = "Vielseitigkeit",
        ["Alternatives"] = "Alternativen",
        ["Worn"] = "Getragen",
        ["worn by the best players"] = "von den besten Spielern getragen",
        ["No data for this specialization."] = "Keine Daten für diese Spezialisierung.",
        ["Nothing matches the filters."] = "Nichts passt zu den Filtern.",
        ["Data of"] = "Daten vom",
        ["Specialization"] = "Spezialisierung",
        ["of %d players"] = "von %d Spielern",
        ["Open the Adventure Guide"] = "Abenteuerführer öffnen",
        ["Left-click opens KeyLootMaster."] = "Linksklick öffnet KeyLootMaster.",
    },
}

local locale = GetLocale and GetLocale() or "enUS"
for key, text in pairs(overrides[locale] or {}) do L[key] = text end
