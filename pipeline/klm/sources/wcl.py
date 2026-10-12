"""What the best raiders wear, from Warcraft Logs' character rankings.

    zone encounters x classes x specializations -> top parses with their gear
      -> per specialization the best `top_per_spec` distinct players
      -> per slot the share of players wearing each item

delivers `entries` records (klm/model.py), content "raid". The API (v2, GraphQL)
returns each ranked player's equipment with the ranking
(`includeCombatantInfo`), so no second lookup is needed.

Credentials: WCL_CLIENT_ID / WCL_CLIENT_SECRET in the environment, else
~/.config/wcl/credentials.env (KEY=VALUE lines).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"
RETRIES = 4
PAUSE = 0.2

# A ranked player's gear list is in the game's slot order. Shirt (3) and tabard
# (17) are left out; both rings and both trinkets fold to one slot.
SLOT_BY_INDEX = {
    0: "head", 1: "neck", 2: "shoulder", 4: "chest", 5: "waist", 6: "legs", 7: "feet",
    8: "wrist", 9: "hands", 10: "finger", 11: "finger", 12: "trinket", 13: "trinket",
    14: "back", 15: "main_hand", 16: "off_hand",
}

CLASSES_QUERY = "query { gameData { classes { id name slug specs { id name slug } } } }"
ZONE_QUERY = "query($zone: Int!) { worldData { zone(id: $zone) { id name encounters { id name } } } }"
RANKINGS_QUERY = """
query($encounter: Int!, $class: String!, $spec: String!, $difficulty: Int!, $page: Int!) {
  worldData { encounter(id: $encounter) {
    characterRankings(className: $class, specName: $spec, difficulty: $difficulty, metric: dps,
                      page: $page, includeCombatantInfo: true)
  } }
}
"""


class WclError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def log(message):
    print(message, file=sys.stderr, flush=True)


def kebab(name):
    """"DeathKnight" -> "death-knight", "BeastMastery" -> "beast-mastery"."""
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower().replace(" ", "-")


def read_credentials(env=None, home=None):
    env = os.environ if env is None else env
    client_id, secret = env.get("WCL_CLIENT_ID"), env.get("WCL_CLIENT_SECRET")
    if not (client_id and secret):
        path = (Path(home) if home else Path.home()) / ".config" / "wcl" / "credentials.env"
        if path.exists():
            values = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
            client_id = client_id or values.get("WCL_CLIENT_ID")
            secret = secret or values.get("WCL_CLIENT_SECRET")
    if not (client_id and secret):
        raise WclError("no Warcraft Logs credentials: set WCL_CLIENT_ID and WCL_CLIENT_SECRET "
                       "or fill ~/.config/wcl/credentials.env")
    return client_id, secret


class Client:
    def __init__(self, client_id, secret, opener=None, sleep=time.sleep):
        self.client_id, self.secret = client_id, secret
        self.opener = opener or self._open
        self.sleep = sleep
        self.token = None

    def _open(self, request):
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def _send(self, request):
        for attempt in range(RETRIES):
            try:
                return self.opener(request)
            except urllib.error.HTTPError as error:
                retry = error.code == 429 or error.code >= 500
                if not retry or attempt == RETRIES - 1:
                    raise WclError(f"HTTP {error.code} for {request.full_url}", status=error.code) from error
                self.sleep(5 * 2 ** attempt)
            except urllib.error.URLError as error:
                if attempt == RETRIES - 1:
                    raise WclError(f"no answer from {request.full_url}: {error.reason}") from error
                self.sleep(5 * 2 ** attempt)

    def authenticate(self):
        basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        request = urllib.request.Request(
            TOKEN_URL, data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"})
        self.token = self._send(request)["access_token"]

    def query(self, text, variables=None):
        if self.token is None:
            self.authenticate()
        request = urllib.request.Request(
            API_URL, data=json.dumps({"query": text, "variables": variables or {}}).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        answer = self._send(request)
        self.sleep(PAUSE)
        if answer.get("errors"):
            raise WclError("; ".join(e.get("message", "?") for e in answer["errors"]))
        return answer["data"]


def classes(client):
    """[(API class slug, our class slug, [(API spec slug, our spec slug), ...])] in API order.

    The rankings query wants the API's own slugs ("DeathKnight", "BeastMastery"),
    not the display names with spaces; ours are the kebab-case of them.
    """
    return [(c["slug"], kebab(c["slug"]), [(s["slug"], kebab(s["slug"])) for s in c["specs"]])
            for c in client.query(CLASSES_QUERY)["gameData"]["classes"]]


def zone_encounters(client, zone):
    found = client.query(ZONE_QUERY, {"zone": zone})["worldData"]["zone"]
    if not found:
        raise WclError(f"no zone {zone}")
    return [e["id"] for e in found["encounters"]]


def worn_by(ranking):
    """slot -> set of item ids, from one ranking's gear list."""
    worn = defaultdict(set)
    for index, piece in enumerate(ranking.get("gear") or []):
        slot = SLOT_BY_INDEX.get(index)
        item = piece.get("id") if isinstance(piece, dict) else None
        if slot and isinstance(item, int) and item > 0:
            worn[slot].add(item)
    return worn


def best_players(boards, top_per_spec):
    """Distinct players of one specialization, best rank first.

    `boards` is a list of ranking lists (one per encounter, best first). A player's
    rank is the best place they hold on any encounter; the gear is the one of that
    parse.
    """
    best = {}
    for rankings in boards:
        for place, ranking in enumerate(rankings):
            server = ranking.get("server") or {}
            key = (ranking.get("name"), server.get("region"), server.get("id"))
            if key[0] is None:
                continue
            if key not in best or place < best[key][0]:
                best[key] = (place, ranking)
    ordered = sorted(best.values(), key=lambda pair: (pair[0], -pair[1].get("amount", 0), pair[1]["name"]))
    return [ranking for _, ranking in ordered[:top_per_spec]]


def entries_for(class_slug, spec_slug, rankings):
    sample = len(rankings)
    counts = defaultdict(Counter)
    for ranking in rankings:
        for slot, items in worn_by(ranking).items():
            for item in items:
                counts[slot][item] += 1
    return [{"class": class_slug, "spec": spec_slug, "content": "raid", "slot": slot, "item": item,
             "share": round(count / sample, 4), "sample": sample}
            for slot in sorted(counts) for item, count in sorted(counts[slot].items())] if sample else []


def fetch_entries(client, zone, difficulty=5, top_per_spec=100, progress=log):
    encounters = zone_encounters(client, zone)
    entries = []
    for class_name, class_slug, specs in classes(client):
        for spec_name, spec_slug in specs:
            boards = []
            for encounter in encounters:
                data = client.query(RANKINGS_QUERY, {"encounter": encounter, "class": class_name, "spec": spec_name,
                                                      "difficulty": difficulty, "page": 1})
                board = (data["worldData"]["encounter"] or {}).get("characterRankings") or {}
                boards.append(board.get("rankings") or [])
            players = best_players(boards, top_per_spec)
            progress(f"{class_slug} {spec_slug}: {len(players)} players")
            entries.extend(entries_for(class_slug, spec_slug, players))
    return entries
