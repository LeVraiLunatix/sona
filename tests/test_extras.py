"""Nouvelles sorties, « il y a un an », mode sport, instrumentales, moments,
carte des écoutes, défis et votes de soirée."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.providers.base import AlbumInfo, TrackInfo
from app.services import artist_photos, instrumental
from app.services.resolver import Candidate
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def play(title, artist, when, **extra):
    return {"title": title, "artist": artist, "source": "deezer", "source_id": extra.pop("sid", title),
            "artist_source_id": extra.pop("aid", None), "duration_seconds": 180,
            "played_at": when.isoformat(), **extra}


class ExtraDeezer:
    def __init__(self):
        today = date.today()
        self.albums = {
            "ninho": ([AlbumInfo("deezer", "a1", "Nouvel album", "Ninho", "ninho", "2026", None, 14, None,
                                 release_date=(today - timedelta(days=3)).isoformat(), record_type="album"),
                       AlbumInfo("deezer", "a0", "Vieil album", "Ninho", "ninho", "2019", None, 14, None,
                                 release_date="2019-01-01", record_type="album")],
                      [AlbumInfo("deezer", "s1", "Single", "Ninho", "ninho", "2026", None, 1, None,
                                 release_date=(today - timedelta(days=10)).isoformat(), record_type="single")]),
        }
        self.tracks = {str(i): TrackInfo("deezer", str(i), f"T{i}", f"A{i % 4}", None, None, 180, None,
                                         bpm=150 + i * 3) for i in range(20)}

    async def get_artist_albums(self, artist_id):
        return self.albums.get(artist_id, ([], []))

    async def get_artist_radio(self, artist_id, limit=25):
        return list(self.tracks.values())

    async def get_chart_tracks(self, limit=50):
        return []

    async def get_track(self, track_id):
        return self.tracks[track_id]


def test_new_releases_from_favourite_artists(client, monkeypatch):
    client.deps.deezer = ExtraDeezer()

    async def ninho(deps, name, source, source_id):
        return ("ninho", "https://photo") if name == "Ninho" else None

    monkeypatch.setattr(artist_photos, "_identify", ninho)
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=me, json={"plays": [play(f"t{i}", "Ninho", now - timedelta(hours=i)) for i in range(3)]})

    got = client.get("/releases", headers=me).json()
    assert [(r["title"], r["kind"]) for r in got] == [("Nouvel album", "Album"), ("Single", "Single")]


def test_memories_from_last_year(client):
    me = login(client, "alice")
    last_year = datetime.now(timezone.utc).replace(microsecond=0)
    last_year = last_year.replace(year=last_year.year - 1)
    client.post("/plays", headers=me, json={"plays": [play("Souvenir", "PNL", last_year, sid="42")]})
    got = client.get("/memories", headers=me, params={"tz": "UTC"}).json()
    assert got[0]["years_ago"] == 1 and got[0]["tracks"][0]["title"] == "Souvenir"


def test_sport_tracks_follow_the_cadence(client, monkeypatch):
    client.deps.deezer = ExtraDeezer()

    async def artists(deps, user_id, count=15):
        return [("A", "a")]

    monkeypatch.setattr("app.services.sport.favourite_artists", artists)
    me = login(client, "alice")
    got = client.get("/sport", headers=me, params={"bpm": 171, "exclude": "7"}).json()
    bpms = [t["bpm"] for t in got]
    assert abs(bpms[0] - 171) <= 3 and "7" not in [t["source_id"] for t in got]


def cand(video_id, title, duration):
    return Candidate(video_id=video_id, title=title, artist="X", album=None, duration_seconds=duration,
                     cover_url=None, is_song=False)


def test_instrumental_needs_the_same_length():
    track = TrackInfo("deezer", "1", "Lettre à une femme", "Ninho", None, None, 157, None)
    assert instrumental.pick(track, [
        cand("remix", "Lettre à une femme (Instrumental Remix)", 157),
        cand("long", "Lettre à une femme instrumental", 190),
        cand("other", "Autre titre instrumental", 157),
        cand("good", "Ninho - Lettre à une femme (Instrumental)", 159),
    ]) == "good"


def test_moments_are_shared_with_friends(client):
    alice, bob = login(client, "alice"), login(client, "bob")
    client.post("/moments/deezer/1", headers=alice, json={"position": 102.5, "emoji": "🔥", "text": "ce passage"})
    moments = client.get("/moments/deezer/1", headers=bob).json()
    assert [(m["emoji"], m["name"], m["is_me"]) for m in moments] == [("🔥", "Alice", False)]
    mine = client.get("/moments/deezer/1", headers=alice).json()[0]
    client.delete(f"/moments/{mine['id']}", headers=bob)  # pas le sien : ignoré
    assert len(client.get("/moments/deezer/1", headers=alice).json()) == 1
    client.delete(f"/moments/{mine['id']}", headers=alice)
    assert client.get("/moments/deezer/1", headers=alice).json() == []


def test_listening_map_groups_places(client):
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=me, json={"plays": [
        play("A", "PNL", now - timedelta(minutes=1), lat=48.8566, lon=2.3522),
        play("B", "PNL", now - timedelta(minutes=2), lat=48.861, lon=2.349),
        play("C", "Ninho", now - timedelta(minutes=3), lat=43.2965, lon=5.3698),
        play("D", "Ninho", now - timedelta(minutes=4)),
    ]})
    places = client.get("/map", headers=me).json()
    assert [p["plays"] for p in places] == [2, 1]
    assert places[0]["top_artist"] == "PNL" and round(places[0]["lat"]) == 49


def test_weekly_challenges_and_badges(client):
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=me, json={"plays": [
        play(f"t{i}", f"Artiste {i}", now - timedelta(minutes=i), album="Album") for i in range(8)
    ]})
    got = client.get("/challenges", headers=me, params={"tz": "UTC"}).json()
    by_id = {c["id"]: c for c in got["challenges"]}
    assert by_id["album"]["done"] is False and by_id["album"]["value"] == 1  # un titre par artiste
    assert by_id["variety"]["value"] == 8
    assert {b["id"] for b in got["badges"]} >= {"plays100", "night"}


def test_party_votes_reorder_the_queue(client):
    host, guest = login(client, "alice"), login(client, "bob")
    code = client.post("/party", headers=host).json()["code"]
    client.post(f"/party/{code}/join", headers=guest)
    track = {"source": "deezer", "source_id": "1", "title": "Premier", "artist": "X"}
    client.post(f"/party/{code}/queue", headers=host, json={"track": track})
    state = client.post(f"/party/{code}/queue", headers=guest, json={"track": {**track, "source_id": "2", "title": "Second"}}).json()
    second = next(q for q in state["queue"] if q["track"]["title"] == "Second")
    state = client.post(f"/party/{code}/queue/{second['id']}/vote", headers=host).json()
    assert [(q["track"]["title"], q["votes"], q["voted"]) for q in state["queue"]] == [("Second", 2, True), ("Premier", 1, True)]
    state = client.post(f"/party/{code}/queue/{second['id']}/vote", headers=host).json()
    assert [q["votes"] for q in state["queue"]] == [1, 1]
