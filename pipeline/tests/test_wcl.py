import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm.model import validate  # noqa: E402
from klm.sources import wcl  # noqa: E402


def gear(*ids):
    return [{"id": i} for i in ids]


def ranking(name, amount, items, region="EU", server=1):
    return {"name": name, "amount": amount, "server": {"id": server, "region": region}, "gear": gear(*items)}


# index: 0 head 1 neck 2 shoulder 3 shirt 4 chest ... 10/11 rings 12/13 trinkets ... 15 main hand 17 tabard
def full(head, ring1, ring2, shirt=999):
    return [head, 10, 20, shirt, 40, 50, 60, 70, 80, 90, ring1, ring2, 120, 130, 140, 150, 160, 170]


class PureTest(unittest.TestCase):
    def test_kebab(self):
        self.assertEqual(wcl.kebab("DeathKnight"), "death-knight")
        self.assertEqual(wcl.kebab("BeastMastery"), "beast-mastery")
        self.assertEqual(wcl.kebab("Paladin"), "paladin")

    def test_worn_by_skips_shirt_tabard_and_empty_slots(self):
        worn = wcl.worn_by({"gear": gear(*full(1, 2, 3))})
        everything = set().union(*worn.values())
        self.assertNotIn(999, everything)  # shirt
        self.assertNotIn(170, everything)  # tabard
        self.assertEqual(worn["head"], {1})
        self.assertEqual(worn["finger"], {2, 3})
        self.assertEqual(wcl.worn_by({"gear": [{"id": 0}]}), {})

    def test_best_players_dedupes_across_encounters_by_best_place(self):
        a1, b1 = ranking("Ann", 100, [1]), ranking("Bob", 90, [2])
        a2, c2 = ranking("Ann", 95, [3]), ranking("Cy", 80, [4])
        best = wcl.best_players([[b1, a1], [a2, c2]], 10)
        self.assertEqual([r["name"] for r in best], ["Ann", "Bob", "Cy"])
        self.assertEqual(best[0]["gear"][0]["id"], 3)  # Ann's best place is first on encounter 2

    def test_same_name_on_two_regions_is_two_players(self):
        best = wcl.best_players([[ranking("Ann", 1, [1], region="EU"), ranking("Ann", 1, [2], region="US", server=9)]], 10)
        self.assertEqual(len(best), 2)

    def test_entries_share_and_sample(self):
        rows = wcl.entries_for("paladin", "protection", [ranking("A", 1, full(1, 2, 3)), ranking("B", 1, full(1, 3, 4))])
        share = {(r["slot"], r["item"]): r["share"] for r in rows}
        self.assertEqual(share[("head", 1)], 1.0)
        self.assertEqual(share[("finger", 3)], 1.0)
        self.assertEqual(share[("finger", 2)], 0.5)
        self.assertTrue(all(r["sample"] == 2 and r["content"] == "raid" for r in rows))
        self.assertEqual(wcl.entries_for("a", "b", []), [])


class FetchTest(unittest.TestCase):
    def test_end_to_end(self):
        queried = set()

        def opener(request):
            if request.full_url == wcl.TOKEN_URL:
                return {"access_token": "t"}
            body = json.loads(request.data)
            text, variables = body["query"], body["variables"]
            if "gameData" in text:
                return {"data": {"gameData": {"classes": [
                    {"name": "Paladin", "slug": "Paladin", "specs": [{"name": "Protection", "slug": "Protection"},
                                                                   {"name": "Holy", "slug": "Holy"}]},
                    {"name": "Demon Hunter", "slug": "DemonHunter",
                     "specs": [{"name": "Beast Mastery", "slug": "BeastMastery"}]}]}}}
            if "zone(id" in text:
                return {"data": {"worldData": {"zone": {"encounters": [{"id": 1}, {"id": 2}]}}}}
            queried.add((variables["class"], variables["spec"]))
            rankings = [ranking("Ann", 100, full(1, 2, 3))] if variables["spec"] in ("Protection", "BeastMastery") else []
            return {"data": {"worldData": {"encounter": {"characterRankings": {"rankings": rankings}}}}}

        client = wcl.Client("i", "s", opener=opener, sleep=lambda s: None)
        entries = wcl.fetch_entries(client, 53, 5, 100, progress=lambda m: None)
        validate({"source": "wcl-raid", "generated": "2026-10-13T00:00:00Z", "entries": entries, "drops": []})
        self.assertEqual({(e["class"], e["spec"]) for e in entries},
                         {("paladin", "protection"), ("demon-hunter", "beast-mastery")})
        self.assertIn(("DemonHunter", "BeastMastery"), queried)  # the API's slugs, not the display names
        self.assertTrue(all(e["sample"] == 1 for e in entries))


class CredentialsTest(unittest.TestCase):
    def test_file_is_read_and_missing_is_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(wcl.WclError):
                wcl.read_credentials({}, home)
            folder = Path(home) / ".config" / "wcl"
            folder.mkdir(parents=True)
            (folder / "credentials.env").write_text("WCL_CLIENT_ID=a\nWCL_CLIENT_SECRET=b\n")
            self.assertEqual(wcl.read_credentials({}, home), ("a", "b"))


if __name__ == "__main__":
    unittest.main()
