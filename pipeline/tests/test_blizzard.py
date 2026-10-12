import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm.model import validate  # noqa: E402
from klm.sources import blizzard  # noqa: E402


def fake_api():
    """A tiny journal: one season dungeon, one raid, one stray raid, the generic dungeon page."""
    pages = {
        "/data/wow/journal-expansion/505": {
            "dungeons": [{"id": 10}, {"id": 99}],
            "raids": [{"id": 20}, {"id": 21}],
        },
        "/data/wow/journal-instance/10": {"id": 10, "name": "Example Keep", "category": {"type": "DUNGEON"},
                                          "encounters": [{"id": 100}, {"id": 101}]},
        "/data/wow/journal-instance/99": {"id": 99, "name": "Keystone Dungeons", "category": {"type": "WORLD"},
                                          "encounters": [{"id": 900}]},
        "/data/wow/journal-instance/20": {"id": 20, "name": "Example Abyss", "category": {"type": "RAID"},
                                          "encounters": [{"id": 200}]},
        "/data/wow/journal-encounter/100": {"id": 100, "name": "First \"Boss\"",
                                            "items": [{"item": {"id": 5001, "name": "A"}},
                                                      {"item": {"id": 5002, "name": "B"}}]},
        "/data/wow/journal-encounter/101": {"id": 101, "name": "Second", "items": [{"item": {"id": 5001}}]},
        "/data/wow/journal-encounter/200": {"id": 200, "name": "Raid Boss", "items": [{"item": {"id": 6001}}, {"junk": 1}]},
    }
    calls = []

    def opener(request):
        url = request.full_url
        if url == blizzard.TOKEN_URL:
            return {"access_token": "t", "expires_in": 86399}
        path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
        calls.append((path, url.split("namespace=", 1)[1].split("&", 1)[0]))
        return pages[path]

    client = blizzard.Client("id", "secret", region="eu", opener=opener, sleep=lambda s: None)
    return client, calls


class FetchDropsTest(unittest.TestCase):
    def test_collects_dungeon_and_chosen_raid_drops(self):
        client, calls = fake_api()
        drops = blizzard.fetch_drops(client, 505, [20])
        self.assertEqual([(d["item"], d["kind"], d["encounter"]) for d in drops],
                         [(5001, "dungeon", 100), (5001, "dungeon", 101), (5002, "dungeon", 100),
                          (6001, "raid", 200)])
        self.assertTrue(all(namespace == "static-eu" for _, namespace in calls))

    def test_the_generic_keystone_page_and_unchosen_raids_are_left_out(self):
        client, calls = fake_api()
        blizzard.fetch_drops(client, 505, [20])
        paths = [p for p, _ in calls]
        self.assertNotIn("/data/wow/journal-encounter/900", paths)
        self.assertNotIn("/data/wow/journal-instance/21", paths)

    def test_a_raid_outside_the_tier_is_an_error(self):
        client, _ = fake_api()
        with self.assertRaises(blizzard.BlizzardError):
            blizzard.fetch_drops(client, 505, [777])

    def test_the_dataset_validates(self):
        client, _ = fake_api()
        result = blizzard.dataset(blizzard.fetch_drops(client, 505, [20]))
        validate(result)
        self.assertEqual(result["source"], "blizzard-journal")
        self.assertEqual(result["entries"], [])


class ClientTest(unittest.TestCase):
    def test_a_server_error_is_retried_then_succeeds(self):
        attempts = []
        waits = []

        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
            return {"ok": True}

        client = blizzard.Client("i", "s", opener=opener, sleep=waits.append)
        self.assertEqual(client.get("/x"), {"ok": True})
        self.assertEqual(len(attempts), 3)
        self.assertTrue(all(w >= 1 for w in waits[:2]))

    def test_a_client_error_is_not_retried(self):
        attempts = []

        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            attempts.append(1)
            raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        with self.assertRaises(blizzard.BlizzardError):
            client.get("/x")
        self.assertEqual(len(attempts), 1)


class CredentialsTest(unittest.TestCase):
    def test_environment_wins_over_the_file(self):
        with tempfile.TemporaryDirectory() as home:
            folder = Path(home) / ".config" / "blizzard"
            folder.mkdir(parents=True)
            (folder / "credentials.env").write_text("BLIZZARD_CLIENT_ID=file\nBLIZZARD_CLIENT_SECRET=filesecret\n")
            self.assertEqual(blizzard.read_credentials({"BLIZZARD_CLIENT_ID": "env", "BLIZZARD_CLIENT_SECRET": "envsecret"}, home),
                             ("env", "envsecret"))
            self.assertEqual(blizzard.read_credentials({}, home), ("file", "filesecret"))

    def test_missing_credentials_are_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(blizzard.BlizzardError):
                blizzard.read_credentials({}, home)


if __name__ == "__main__":
    unittest.main()
