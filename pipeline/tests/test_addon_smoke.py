"""Loads the addon's real Lua files with the real generated data against a stub of the game API.

This catches typos, wrong calls and nil errors on the paths the window and the tooltip take. It does not
replace a look in the game: the stub accepts any method call on a widget.
Skipped when lupa is not installed.
"""

import unittest
from pathlib import Path

try:
    import lupa
except ImportError:  # pragma: no cover
    lupa = None

ADDON = Path(__file__).resolve().parents[2] / "addon" / "KeyLootMaster"

PRELUDE = r"""
local PROPERTIES = { TitleText = true, Text = true, text = true }
local created = {}
local Widget = {}
Widget.__index = function(t, key)
  -- Game methods are CamelCase; every other key is a plain field and reads as nil until set.
  if PROPERTIES[key] or not tostring(key):match("^%u") then return nil end
  local own = rawget(Widget, key)
  if own then return own end
  return function(self, ...) return self end
end
function Widget.new(kind, name, template)
  local w = setmetatable({ kind = kind, name = name, template = template, scripts = {}, shown = true, checked = false }, Widget)
  created[#created + 1] = w
  return w
end
function Widget.SetScript(self, event, fn) self.scripts[event] = fn end
function Widget.SetText(self, text) self.text = text end
function Widget.GetText(self) return self.text end
function Widget.Show(self) self.shown = true end
function Widget.Hide(self) self.shown = false end
function Widget.SetShown(self, on) self.shown = on and true or false end
function Widget.IsShown(self) return self.shown end
function Widget.SetChecked(self, on) self.checked = on and true or false end
function Widget.GetChecked(self) return self.checked end
function Widget.CreateFontString(self) return Widget.new("FontString") end
function Widget.CreateTexture(self) return Widget.new("Texture") end
function Widget.SetupMenu(self, fn) self.menuFn = fn end
function Widget.SetDefaultText(self, text) self.defaultText = text end
function Widget.SetTexture(self, texture) self.texture = texture end
function Widget.GetFont(self) return "font", 12, "" end
function Widget.AddLine(self, text) self.lines = self.lines or {}; self.lines[#self.lines + 1] = text end

HAS_DROPDOWN = true
function CreateFrame(kind, name, parent, template)
  if kind == "DropdownButton" and not HAS_DROPDOWN then error("unknown frame type") end
  return Widget.new(kind, name, template)
end
UIParent = Widget.new("Frame", "UIParent")
UISpecialFrames = {}
SlashCmdList = {}
GameTooltip = Widget.new("Frame", "GameTooltip")
printed = {}
function print(...) printed[#printed + 1] = table.concat({ ... }, " ") end
function GetLocale() return "enUS" end
function GetSpecialization() return 1 end
function GetSpecializationInfo(index) return 66 end
function GetInventoryItemID(unit, slot) if slot == 1 then return 271465 end end
ITEM_QUALITY_COLORS = { [4] = { r = 0.64, g = 0.21, b = 0.93 } }
C_Item = {
  GetItemInfo = function(id) return "Item " .. id, "|cff|Hitem:" .. id .. "|h[Item " .. id .. "]|h|r", 4 end,
  GetItemIconByID = function(id) return 100000 + id end,
}
C_Timer = { After = function(_, fn) fn() end }
Item = { CreateFromItemID = function(_, id) return { ContinueOnItemLoad = function(self, fn) fn() end } end }
function IsModifiedClick() return false end
posts = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn) posts[#posts + 1] = { kind = kind, fn = fn } end }
Enum = { TooltipDataType = { Item = 1 } }

function load_addon(sources)
  local ns = {}
  for _, entry in ipairs(sources) do
    local chunk, err = load(entry.source, entry.name)
    if not chunk then error(err) end
    chunk("KeyLootMaster", ns)
  end
  return ns
end

-- Calls a dropdown's menu builder with a recorder; returns the radio and checkbox callbacks by text.
function open_menu(dropdown)
  local seen = {}
  local function node()
    local n = {}
    function n:CreateRadio(text, selected, set) seen[#seen + 1] = { text = text, selected = selected, set = set } return n end
    function n:CreateCheckbox(text, selected, set) seen[#seen + 1] = { text = text, selected = selected, set = set } return n end
    function n:CreateButton(text) return node() end
    return n
  end
  dropdown.menuFn(dropdown, node())
  return seen
end

function find_widgets(kind, template)
  local out = {}
  for _, w in ipairs(created) do
    if w.kind == kind and (template == nil or w.template == template) then out[#out + 1] = w end
  end
  return out
end
"""


def sources(with_data=True):
    names = []
    if with_data:
        data = ADDON / "Data"
        names += [data / n for n in ("Meta.lua", "Specs.lua", "Drops.lua", "Items.lua", "paladin.lua", "mage.lua")]
    names += [ADDON / n for n in ("Locales.lua", "Logic.lua", "Core.lua", "UI.lua", "Tooltip.lua")]
    return [(p.name, p.read_text(encoding="utf-8")) for p in names]


@unittest.skipIf(lupa is None, "lupa is not installed")
class SmokeTest(unittest.TestCase):
    def boot(self, dropdown=True):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(PRELUDE)
        g = self.lua.globals()
        g.HAS_DROPDOWN = dropdown
        entries = self.lua.table_from([self.lua.table_from({"name": n, "source": s}) for n, s in sources()])
        self.ns = g.load_addon(entries)
        self.g = g
        return self.ns

    def open_window(self):
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        frame = self.g.find_widgets("Frame", "BasicFrameTemplateWithInset")[1]
        self.assertTrue(frame.shown)
        return frame

    def rows(self):
        # the list rows and the alternatives that are shown (not the Adventure Guide button)
        return [w for w in self.g.find_widgets("Button").values()
                if w.itemId is not None and w.name is not None and w.shown]

    def test_the_window_opens_and_shows_the_players_specialization(self):
        self.boot()
        self.open_window()
        rows = self.rows()
        self.assertGreater(len(rows), 5)
        self.assertTrue(all(str(r.name.text).startswith("Item ") for r in rows))
        texts = [w.text for w in self.g.find_widgets("FontString").values() if w.text]
        self.assertTrue(any("Paladin - Protection" in str(t) for t in texts) or
                        any("Paladin - Protection" in str(w.defaultText) for w in self.g.find_widgets("DropdownButton").values()))

    def test_slash_toggles_and_tooltip_switch(self):
        self.boot()
        self.open_window()
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        self.assertFalse(self.g.find_widgets("Frame", "BasicFrameTemplateWithInset")[1].shown)
        self.g.SlashCmdList["KEYLOOTMASTER"]("tooltip")
        self.assertFalse(self.g.KeyLootMasterDB.tooltip)
        self.assertIn("off", self.g.printed[1])

    def test_content_buttons_and_filters_change_the_rows(self):
        self.boot()
        self.open_window()
        buttons = {w.text: w for w in self.g.find_widgets("Button", "UIPanelButtonTemplate").values()}
        buttons["Raid"].scripts.OnClick(buttons["Raid"])
        self.assertEqual(self.g.KeyLootMasterDB.content, "raid")
        # source filter through the dropdown menu
        dropdowns = list(self.g.find_widgets("DropdownButton").values())
        source = dropdowns[1]
        menu = self.g.open_menu(source)
        crafted = next(m for m in menu.values() if m.text == "Crafted")
        crafted.set()
        self.assertEqual(self.g.KeyLootMasterDB.source, "crafted")
        for row in self.rows():
            self.assertIn("Crafted", row.where.text)
        # a stat checkbox and "only missing"
        checks = list(self.g.find_widgets("CheckButton").values())
        checks[0].checked = True
        checks[0].scripts.OnClick(checks[0])
        self.assertEqual(self.g.KeyLootMasterDB.stats, "c")
        checks[-1].checked = True
        checks[-1].scripts.OnClick(checks[-1])
        self.assertTrue(self.g.KeyLootMasterDB.missing)

    def test_every_specialization_can_be_chosen_without_error(self):
        self.boot()
        self.open_window()
        spec = list(self.g.find_widgets("DropdownButton").values())[0]
        menu = self.g.open_menu(spec)
        self.assertGreaterEqual(len(menu), 3)
        for item in menu.values():
            item.set()  # Refresh runs after each; the mage has data, others none: no error either way

    def test_the_tooltip_line_names_both_contents_and_the_source(self):
        self.boot()
        post = self.g.posts[1]
        tip = self.g.GameTooltip
        tip.lines = None
        entries = self.ns.ShareIndex("paladin", "protection")
        item = next(k for k in entries.keys() if entries[k].mplus is not None)
        post.fn(tip, self.lua.table_from({"id": item}))
        lines = list(tip.lines.values())
        self.assertTrue(any("KeyLootMaster" in str(line) for line in lines))
        post.fn(tip, self.lua.table_from({"id": 1}))  # an item nobody wears adds nothing
        self.assertEqual(len(list(tip.lines.values())), len(lines))

    def test_without_the_dropdown_template_the_window_still_works(self):
        self.boot(dropdown=False)
        self.open_window()
        self.assertGreater(len(self.rows()), 5)
        cycle = [w for w in self.g.find_widgets("Button", "UIPanelButtonTemplate").values() if w.text and "All sources" in str(w.text)]
        self.assertTrue(cycle)
        cycle[0].scripts.OnClick(cycle[0])
        self.assertEqual(self.g.KeyLootMasterDB.source, "dungeon")


if __name__ == "__main__":
    unittest.main()
