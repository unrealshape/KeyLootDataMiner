"""Where items drop, from Blizzard's Game Data API (the Adventure Journal).

    expansion ("Current Season" tier) -> instances (dungeons, raids)
      -> encounters -> items

delivers `drops` records (klm/model.py). Entries (what the best players wear)
come from other sources.

Credentials: BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in the environment,
else ~/.config/blizzard/credentials.env (KEY=VALUE lines). The token (24 h) is
fetched with the client-credentials flow and kept in memory only.

Blizzard allows 100 requests a second and 36,000 an hour; a run needs a few
hundred, one at a time, and retries a 429 or a server error with a pause.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOKEN_URL = "https://oauth.battle.net/token"
API_HOST = "https://{region}.api.blizzard.com"
RETRIES = 4
PAUSE = 0.05


class BlizzardError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def read_credentials(env=None, home=None):
    """(client_id, client_secret) from the environment, else the credentials file."""
    env = os.environ if env is None else env
    client_id, secret = env.get("BLIZZARD_CLIENT_ID"), env.get("BLIZZARD_CLIENT_SECRET")
    if not (client_id and secret):
        path = (Path(home) if home else Path.home()) / ".config" / "blizzard" / "credentials.env"
        if path.exists():
            values = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
            client_id = client_id or values.get("BLIZZARD_CLIENT_ID")
            secret = secret or values.get("BLIZZARD_CLIENT_SECRET")
    if not (client_id and secret):
        raise BlizzardError("no Blizzard credentials: set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET "
                            "or fill ~/.config/blizzard/credentials.env")
    return client_id, secret


class Client:
    """A small Game Data API client. `opener` is a test seam: a callable
    (request) -> parsed JSON."""

    def __init__(self, client_id, secret, region="eu", opener=None, sleep=time.sleep):
        self.client_id, self.secret, self.region = client_id, secret, region
        self.opener = opener or self._open
        self.sleep = sleep
        self.token = None

    def _open(self, request):
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def _send(self, request):
        for attempt in range(RETRIES):
            try:
                return self.opener(request)
            except urllib.error.HTTPError as error:
                retry = error.code == 429 or error.code >= 500
                if not retry or attempt == RETRIES - 1:
                    raise BlizzardError(f"HTTP {error.code} for {request.full_url.split('?')[0]}",
                                        status=error.code) from error
                self.sleep(2 ** attempt)
            except urllib.error.URLError as error:
                if attempt == RETRIES - 1:
                    raise BlizzardError(f"no answer from {request.full_url.split('?')[0]}: {error.reason}") from error
                self.sleep(2 ** attempt)

    def authenticate(self):
        basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        request = urllib.request.Request(
            TOKEN_URL, data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"})
        self.token = self._send(request)["access_token"]

    def get(self, path, namespace="static"):
        if self.token is None:
            self.authenticate()
        query = urllib.parse.urlencode({"namespace": f"{namespace}-{self.region}", "locale": "en_US"})
        request = urllib.request.Request(
            API_HOST.format(region=self.region) + path + "?" + query,
            headers={"Authorization": "Bearer " + self.token})
        result = self._send(request)
        self.sleep(PAUSE)
        return result


def fetch_drops(client, expansion, raids, dungeons=None):
    """The drops of a season's dungeons and the chosen raids.

    `expansion` is a journal tier id (505, "Current Season"); `raids` the raid
    instance ids wanted; `dungeons` the dungeon ids, or None for every dungeon
    the tier lists (its generic "Keystone Dungeons" page has no loot of its own).
    """
    tier = client.get(f"/data/wow/journal-expansion/{expansion}")
    wanted = [(d["id"], "dungeon") for d in tier.get("dungeons", [])
              if dungeons is None or d["id"] in dungeons]
    wanted += [(r["id"], "raid") for r in tier.get("raids", []) if r["id"] in raids]
    missing = [r for r in raids if r not in {i for i, k in wanted if k == "raid"}]
    if missing:
        raise BlizzardError(f"raid(s) {missing} are not in journal tier {expansion}")
    drops = []
    for instance_id, kind in wanted:
        instance = client.get(f"/data/wow/journal-instance/{instance_id}")
        if instance.get("category", {}).get("type") not in ("DUNGEON", "RAID"):
            continue
        for encounter_ref in instance.get("encounters", []):
            encounter = client.get(f"/data/wow/journal-encounter/{encounter_ref['id']}")
            for entry in encounter.get("items", []):
                item = entry.get("item") or {}
                if not isinstance(item.get("id"), int):
                    continue
                drops.append({"item": item["id"], "kind": kind,
                              "instance": instance["id"], "instance_name": instance["name"],
                              "encounter": encounter["id"], "encounter_name": encounter["name"]})
    drops.sort(key=lambda d: (d["item"], d["instance"], d["encounter"]))
    return drops


def make_dataset(source, entries=(), drops=(), items=(), specs=None, now=None, stats=(), players=()):
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"source": source, "generated": stamp, "entries": list(entries), "drops": list(drops),
            "items": list(items), "specs": dict(specs or {}), "stats": list(stats), "players": list(players)}


def dataset(drops, now=None):
    return make_dataset("blizzard-journal", drops=drops, now=now)
