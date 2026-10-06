"""Radio « artistes inconnus », mix selon la météo, classements entre amis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.providers.base import ArtistInfo, TrackInfo
from app.services import discover
from tests.test_extras import play
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def tr(sid, artist):
    return TrackInfo("deezer", sid, f"Titre {sid}", artist, None, None, 180, None)


class DiscoverDeezer:
    async def get_related_artists(self, artist_id):
        return [ArtistInfo("deezer", "k", "Connu", None), ArtistInfo("deezer", "n1", "Neuf Un", None),
                ArtistInfo("deezer", "n2", "Neuf Deux", None)]

    async def get_artist_top_tracks(self, artist_id):
        name = {"n1": "Neuf Un", "n2": "Neuf Deux", "k": "Connu"}[artist_id]
        return [tr(f"{artist_id}-{i}", name) for i in range(5)]

    async def get_radio_tracks(self, radio_id):
        return [tr(f"r{radio_id}-{i}", "Radio") for i in range(10)]


def test_unknown_artists_radio_skips_known_artists(client):
    client.deps.deezer = DiscoverDeezer()
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=me, json={"plays": [play("x", "Connu", now - timedelta(days=2))]})
    got = client.get("/discover/radio/deezer/seed", headers=me, params={"artist": "Graine"}).json()
    assert {t["artist"] for t in got} == {"Neuf Un", "Neuf Deux"}
    # Mélangés artiste par artiste, 3 titres chacun.
    assert [t["artist"] for t in got[:2]] == ["Neuf Un", "Neuf Deux"] and len(got) == 6


def test_mood_follows_time_and_weather():
    friday_night = datetime(2026, 10, 9, 21, 0)
    assert discover.pick_mood(friday_night) == "soiree"
    assert discover.pick_mood(datetime(2026, 10, 6, 2, 0)) == "nuit"
    tuesday = datetime(2026, 10, 6, 15, 0)
    assert discover.pick_mood(tuesday, code=63, temperature=12) == "pluie"
    assert discover.pick_mood(tuesday, code=0, temperature=27) == "soleil"
    assert discover.pick_mood(tuesday, code=3, temperature=15) == "gris"
    assert discover.pick_mood(datetime(2026, 10, 6, 8, 0)) == "matin"
    assert discover.weather_label(61) == "Pluie"


def test_mood_endpoint_without_location(client):
    client.deps.deezer = DiscoverDeezer()
    me = login(client, "alice")
    got = client.get("/home/mood", headers=me, params={"tz": "Europe/Paris"}).json()
    assert got["mood"] in discover.MOODS and got["title"] and len(got["tracks"]) == 20
    assert got["weather"] is None


def test_friends_leaderboard(client):
    alice = login(client, "alice")
    bob = login(client, "bob")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=alice, json={"plays": [play(f"a{i}", f"Art{i}", now - timedelta(seconds=5 * i)) for i in range(3)]})
    client.post("/plays", headers=bob, json={"plays": [play(f"b{i}", "Solo", now - timedelta(seconds=5 * i)) for i in range(6)]})
    got = client.get("/challenges", headers=alice, params={"tz": "UTC"}).json()["friends"]
    minutes = next(b for b in got["boards"] if b["id"] == "minutes")
    assert [r["me"] for r in minutes["ranking"]] == [False, True]
    assert minutes["ranking"][0]["value"] == 18 and minutes["ranking"][1]["value"] == 9
    artists = next(b for b in got["boards"] if b["id"] == "artists")
    assert artists["ranking"][0]["me"] is True


def test_no_friends_no_boards(client):
    alice = login(client, "alice")
    assert client.get("/challenges", headers=alice, params={"tz": "UTC"}).json()["friends"] == {"boards": [], "champion": None}
