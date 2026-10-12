import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm.model import validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear  # noqa: E402


def member(name, spec, realm="tarren-mill"):
    return {"profile": {"name": name, "realm": {"slug": realm}}, "specialization": {"id": spec}}


def fake_client():
    boards = {
        ("1", "249", "7"): {"leading_groups": [
            {"keystone_level": 20, "completed_timestamp": 5, "members": [member("Tank", 66), member("Heal", 65)]},
            {"keystone_level": 18, "completed_timestamp": 9, "members": [member("Tank", 66), member("Other", 66)]},
        ]},
        ("1", "250", "7"): {"leading_groups": [
            {"keystone_level": 22, "completed_timestamp": 1, "members": [member("Other", 66), member("Gone", 66)]},
        ]},
    }
    gear = {
        "tank": {"HEAD": 100, "FINGER_1": 200, "FINGER_2": 201, "TRINKET_1": 300, "MAIN_HAND": 400},
        "other": {"HEAD": 100, "FINGER_1": 201, "TRINKET_2": 300},
    }

    def opener(request):
        url = request.full_url
        if url == blizzard.TOKEN_URL:
            return {"access_token": "t"}
        path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
        if path == "/data/wow/mythic-keystone/season/index":
            return {"current_season": {"id": 18}}
        if path == "/data/wow/mythic-keystone/season/18":
            return {"periods": [{"id": 6}, {"id": 7}]}
        if path == "/data/wow/connected-realm/index":
            return {"connected_realms": [{"href": "https://x/data/wow/connected-realm/1?namespace=dynamic-eu"}]}
        if path == "/data/wow/connected-realm/1/mythic-leaderboard/index":
            return {"current_leaderboards": [{"id": 249}, {"id": 250}]}
        if path.startswith("/data/wow/connected-realm/1/mythic-leaderboard/"):
            _, _, _, _, _, _, dungeon, _, period = path.split("/")
            if (("1", dungeon, period)) not in boards:
                raise urllib.error.HTTPError(url, 404, "none", {}, None)
            return boards[("1", dungeon, period)]
        if path in ("/data/wow/playable-specialization/66", "/data/wow/playable-specialization/65"):
            return {"name": "Protection" if path.endswith("66") else "Holy", "playable_class": {"name": "Paladin"}}
        if path.startswith("/profile/wow/character/tarren-mill/"):
            name = path.rsplit("/", 2)[1]
            if name not in gear:
                raise urllib.error.HTTPError(url, 404, "gone", {}, None)
            return {"equipped_items": [{"slot": {"type": slot}, "item": {"id": item}}
                                       for slot, item in gear[name].items()]}
        raise AssertionError(path)

    return blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)


class ScanTest(unittest.TestCase):
    def test_a_character_keeps_its_best_group(self):
        client = fake_client()
        found = blizzard_gear.scan_leaderboards(client, [1], [249, 250], [6, 7], progress=lambda m: None)
        self.assertEqual(found[("tarren-mill", "tank")]["level"], 20)
        self.assertEqual(found[("tarren-mill", "other")]["level"], 22)

    def test_pick_best_orders_by_level_and_cuts(self):
        client = fake_client()
        found = blizzard_gear.scan_leaderboards(client, [1], [249, 250], [7], progress=lambda m: None)
        best = blizzard_gear.pick_best(found, 2)
        # Gone and Other share level 22 and time: the name breaks the tie.
        self.assertEqual([c["name"] for c in best[66]], ["Gone", "Other"])
        self.assertEqual([c["name"] for c in best[65]], ["Heal"])


class EntriesTest(unittest.TestCase):
    def test_shares_count_a_ring_or_trinket_in_either_place(self):
        tank = {"head": {100}, "finger": {200, 201}, "trinket": {300}, "main_hand": {400}}
        other = {"head": {100}, "finger": {201}, "trinket": {300}}
        rows = blizzard_gear.entries_for(("paladin", "protection"), [tank, other])
        share = {(r["slot"], r["item"]): r["share"] for r in rows}
        self.assertEqual(share[("head", 100)], 1.0)
        self.assertEqual(share[("finger", 201)], 1.0)
        self.assertEqual(share[("finger", 200)], 0.5)
        self.assertEqual(share[("trinket", 300)], 1.0)
        self.assertEqual(share[("main_hand", 400)], 0.5)
        self.assertTrue(all(r["sample"] == 2 for r in rows))

    def test_nobody_read_gives_nothing(self):
        self.assertEqual(blizzard_gear.entries_for(("a", "b"), []), [])


class FetchTest(unittest.TestCase):
    def test_end_to_end_with_an_unreadable_character_skipped(self):
        entries = blizzard_gear.fetch_entries(fake_client(), top_per_spec=3, periods=1, progress=lambda m: None)
        validate(blizzard.make_dataset("blizzard-mplus", entries=entries))
        protection = [e for e in entries if e["spec"] == "protection"]
        self.assertTrue(protection)
        self.assertTrue(all(e["sample"] == 2 for e in protection))  # "Gone" has no profile
        self.assertTrue(all(e["content"] == "mplus" and e["class"] == "paladin" for e in entries))
        holy = [e for e in entries if e["spec"] == "holy"]
        self.assertEqual(holy, [])  # "Heal" has no profile: nobody read, nothing delivered


if __name__ == "__main__":
    unittest.main()
