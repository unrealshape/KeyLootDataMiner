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
Minimap = Widget.new("Frame", "Minimap")
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
        names += [data / n for n in ("Meta.lua", "Specs.lua", "Drops.lua", "Items.lua", "Bonus.lua", "paladin.lua", "mage.lua")]
    names += [ADDON / n for n in ("Locales.lua", "Logic.lua", "Core.lua", "UI.lua", "Pages.lua", "Tooltip.lua", "Minimap.lua")]
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

    def test_the_minimap_button_shows_opens_the_window_and_hides_by_slash(self):
        ns = self.boot()
        ns.RefreshMinimapButton()
        buttons = self.g.find_widgets("Button")
        button = [w for w in buttons.values() if w.name == "KeyLootMasterMinimapButton"][0]
        self.assertTrue(button.shown)
        button.scripts["OnClick"](button)
        self.assertTrue(self.g.find_widgets("Frame", "BasicFrameTemplateWithInset")[1].shown)
        self.g.SlashCmdList["KEYLOOTMASTER"]("minimap")
        self.assertFalse(button.shown)
        self.assertTrue(self.g.KeyLootMasterDB.minimapHide)
        self.g.SlashCmdList["KEYLOOTMASTER"]("minimap")
        self.assertTrue(button.shown)

    def test_the_top_item_per_slot_carries_a_bis_tag(self):
        self.boot()
        self.open_window()
        rows = self.rows()
        self.assertTrue(any("[BiS]" in str(r.name.text) for r in rows))

    def test_right_click_cycles_the_players_own_mark(self):
        self.boot()
        self.open_window()
        row = self.rows()[0]
        row.scripts.OnClick(row, "RightButton")
        self.assertIn("* Important", str(self.rows()[0].name.text))
        row = self.rows()[0]
        row.scripts.OnClick(row, "RightButton")
        self.assertIn("* Interesting", str(self.rows()[0].name.text))
        row = self.rows()[0]
        row.scripts.OnClick(row, "RightButton")
        self.assertNotIn("* ", str(self.rows()[0].name.text))

    def test_the_mythic_plus_button_lists_only_dungeon_items(self):
        ns = self.boot()
        self.open_window()
        buttons = {w.text: w for w in self.g.find_widgets("Button", "UIPanelButtonTemplate").values()}
        for row in self.rows():
            self.assertTrue(ns.KindsOf(row.itemId).dungeon)
        buttons["Raid"].scripts.OnClick(buttons["Raid"])
        for row in self.rows():
            self.assertTrue(ns.KindsOf(row.itemId).raid)
        buttons["Mythic+"].scripts.OnClick(buttons["Mythic+"])
        # the filter can be switched off, and the choice is saved
        self.assertTrue(self.g.KeyLootMasterDB.farmable)
        checks = list(self.g.find_widgets("CheckButton").values())
        checks[-1].checked = False
        checks[-1].scripts.OnClick(checks[-1])
        self.assertFalse(self.g.KeyLootMasterDB.farmable)
        self.assertTrue(any(not ns.KindsOf(r.itemId).dungeon for r in self.rows()))

    def test_dungeon_items_show_what_the_chosen_key_level_rewards(self):
        ns = self.boot()
        self.open_window()
        self.assertIn("292 Champion 1/6", str(self.rows()[0].where.text))
        self.g.KeyLootMasterDB.keyLevel = 8
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        self.assertIn("308 Hero 2/6", str(self.rows()[0].where.text))
        self.g.KeyLootMasterDB.vault = True
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        self.g.SlashCmdList["KEYLOOTMASTER"]("")
        self.assertIn("315 Hero 4/6", str(self.rows()[0].where.text))

    def test_the_key_levels_group_what_rewards_the_same(self):
        ns = self.boot()
        groups = ns.KeyGroups(False)
        self.assertEqual(groups[2].label, "+2-+3")
        self.assertEqual(groups[2].ilvl, 295)
        self.assertEqual(groups[len(groups)].label, "+10+")

    def test_filters_are_kept_per_specialization(self):
        ns = self.boot()
        self.open_window()
        db = self.g.KeyLootMasterDB
        db.keyLevel = 8
        db.stats = "c"
        ns.UseProfile("mage-fire")        # the filters of the first one are put away
        self.assertEqual(db.keyLevel, 8)   # a specialization without saved filters keeps the ones in use
        db.keyLevel = 2
        ns.UseProfile("paladin-protection")
        self.assertEqual(db.keyLevel, 8)   # ...and the first one gets its own back
        self.assertEqual(db.stats, "c")

    STATS = ('KeyLootMasterStats = { paladin = { protection = { n = 50, c = {1111, 33.2}, h = {1019, 29.0}, '
             'm = {521, 23.1}, v = {297, 6.0}, leech = {282, 4.0}, avoidance = {39, 1.0}, speed = {0, 2.0} } } }')

    def test_stats_are_ranked_from_the_highest_rating_down(self):
        ns = self.boot()
        self.lua.execute(self.STATS)
        stats = ns.StatsOf("paladin", "protection")
        order = [r.key for r in ns.StatRanking(stats, ns.MAIN_STATS).values()]
        self.assertEqual(order, ["c", "h", "m", "v"])
        minor = [r.key for r in ns.StatRanking(stats, ns.MINOR_STATS).values()]
        self.assertEqual(minor, ["leech", "avoidance", "speed"])
        self.assertIsNone(ns.StatsOf("mage", "fire"))

    def page_button(self, label):
        return [w for w in self.g.find_widgets("Button", "UIPanelButtonTemplate").values() if w.text == label][0]

    def shown_texts(self):
        return [str(w.text) for w in self.g.find_widgets("FontString").values() if w.text and w.shown]

    def test_the_stats_page_replaces_the_list_and_comes_back(self):
        ns = self.boot()
        self.lua.execute(self.STATS)
        self.open_window()
        self.assertTrue(len(self.rows()) > 5)
        stats = self.page_button("Stats")
        stats.scripts.OnClick(stats)
        self.assertEqual(len(self.rows()), 0)
        texts = self.shown_texts()
        self.assertTrue(any("CRIT" in s and "HASTE" in s for s in texts))
        self.assertTrue(any("+1111" in s for s in texts))
        items = self.page_button("Items")
        items.scripts.OnClick(items)
        self.assertTrue(len(self.rows()) > 5)

    GEAR = (
        'KeyLootMasterGear = { paladin = { protection = { mplus = { n = 50, '
        'enchants = { head = { {id = 8017, name = "Empowered Hex of Leeching", n = 42}, {id = 8018, name = "Hex of Leeching", n = 3} } }, '
        'gems = { {id = 240898, name = "Flawless Deadly Amethyst", color = "purple", n = 8} }, '
        'gemSets = { { sig = { meta = 1, green = 2, red = 1 }, n = 21 } }, '
        'embellishments = { {id = 1, name = "Arcanoweave Lining", n = 41} }, '
        'builds = { {code = "CYQALMl7AwW51MWzGneuHE3tPCAAAAzMbbzMGjZZ", n = 17, hero = "Lightsmith"} }, '
        'talents = { {id = 1, name = "Holy Bulwark", n = 50, tree = "spec"} }, '
        'heroes = { {name = "Lightsmith", n = 48} }, '
        'players = { {name = "Pinkzilla", realm = "Silvermoon", region = "eu", race = "Dwarf", ilvl = 333, rating = 4042} } '
        '} } } }')

    def test_the_gear_talent_and_player_pages_show_their_data(self):
        ns = self.boot()
        self.lua.execute(self.GEAR)
        self.open_window()
        for label, needle in (("Gear", "Empowered Hex of Leeching"), ("Talents", "Holy Bulwark"), ("Players", "Pinkzilla")):
            button = self.page_button(label)
            button.scripts.OnClick(button)
            self.assertEqual(len(self.rows()), 0)
            self.assertTrue(any(needle in s for s in self.shown_texts()), label)
            if label == "Gear":
                self.assertTrue(any("1 Meta, 1 Red, 2 Green" in s for s in self.shown_texts()))

    def test_the_pages_say_so_when_there_is_no_data(self):
        self.boot()
        self.open_window()
        button = self.page_button("Gear")
        button.scripts.OnClick(button)
        self.assertTrue(any("Noch keine" in s or "No gear data" in s for s in self.shown_texts()))

    def test_gem_signatures_read_and_compare(self):
        ns = self.boot()
        self.assertEqual(ns.GemColorOf("Flawless Deadly Peridot"), "green")
        self.assertEqual(ns.GemColorOf("Indecipherable Eversong Diamond"), "meta")
        top = self.lua.table_from({"meta": 1, "green": 2, "red": 1})
        own = self.lua.table_from({"meta": 1, "green": 1})
        self.assertEqual(ns.SigDiff(own, top, None), "+1 Red, +1 Green")
        self.assertEqual(ns.SigText(top, None), "1 Meta, 1 Red, 2 Green")

    def test_the_copy_button_opens_the_import_string(self):
        ns = self.boot()
        self.lua.execute(self.GEAR)
        self.open_window()
        button = self.page_button("Talents")
        button.scripts.OnClick(button)
        copy = [w for w in self.g.find_widgets("Button", "UIPanelButtonTemplate").values() if w.text == "Build kopieren" or w.text == "Copy build"][0]
        copy.scripts.OnClick(copy)
        box = self.g.find_widgets("Frame", "BasicFrameTemplateWithInset")
        self.assertTrue(len(box) >= 2)

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
        source = dropdowns[2]  # specialization, key level, source
        menu = self.g.open_menu(source)
        crafted = next(m for m in menu.values() if m.text == "Crafted")
        crafted.set()
        self.assertEqual(self.g.KeyLootMasterDB.source, "crafted")
        for row in self.rows():
            self.assertIn("Crafted", row.where.text)
        # a stat checkbox and "only missing"
        checks = list(self.g.find_widgets("CheckButton").values())
        checks[1].checked = True  # checks[0] is the Great Vault box
        checks[1].scripts.OnClick(checks[1])
        self.assertEqual(self.g.KeyLootMasterDB.stats, "c")
        checks[-2].checked = True
        checks[-2].scripts.OnClick(checks[-2])
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
