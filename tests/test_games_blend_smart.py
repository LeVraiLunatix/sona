"""« Complète les paroles », Blend entre amis et playlists intelligentes."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.providers.base import TrackInfo
from app.providers.lrclib import Lyrics, LyricsLine
from app.services import lyricsgame
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def song_lines():
    words = ["je", "roule", "la", "nuit", "sous", "les", "étoiles", "du", "quartier", "encore"]
    return [LyricsLine(12.0 + i * 4, " ".join(words[i % 3: i % 3 + 5]) + f" mot{i}") for i in range(20)]


def test_lyrics_question_hides_the_end_of_a_line():
    track = TrackInfo("deezer", "1", "Titre", "Artiste", None, None, 200, "https://cover")
    q = lyricsgame.question_from(track, song_lines(), random.Random(3), [])
    assert q is not None and q["kind"] == "lyrics"
    answer = q["choices"][q["answer"]]["title"]
    assert len({c["title"] for c in q["choices"]}) == 4
    assert q["prompt"].endswith("…") and answer not in q["prompt"]
    assert q["clip_start"] == q["line_time"] - lyricsgame.LEAD_IN
    assert len(q["before"]) == 2


def test_lyrics_round_through_the_blind_test(client):
    class FakeLrclib:
        async def get_lyrics(self, title, artist, album=None, duration=None):
            return Lyrics(synced=True, lines=song_lines())

    class Deezer:
        async def get_chart_tracks(self, limit=50):
            return [TrackInfo("deezer", str(i), f"T{i}", f"A{i}", None, None, 200, None) for i in range(6)]

    client.deps.lrclib = FakeLrclib()
    client.deps.deezer = Deezer()
    me = login(client, "alice")
    got = client.get("/blindtest/round", headers=me, params={"mode": "chart", "count": 4, "guess": "lyrics"}).json()
    assert got["guess"] == "lyrics" and len(got["questions"]) == 4
    assert all(q["kind"] == "lyrics" for q in got["questions"])


def plays(titles, when, artist="X"):
    return [{"title": t, "artist": artist, "source": "deezer", "source_id": t, "duration_seconds": 180,
             "played_at": (when - timedelta(minutes=i)).isoformat()} for i, t in enumerate(titles)]


def test_blend_mixes_both_tastes(client):
    alice, bob = login(client, "alice"), login(client, "bob")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=alice, json={"plays": plays(["Commun", "A1", "A2"] * 5, now)})
    client.post("/plays", headers=bob, json={"plays": plays(["Commun", "B1", "B2"] * 5, now - timedelta(hours=1))})
    bob_id = next(f["account_id"] for f in client.get("/friends", headers=alice).json())
    blend = client.get(f"/friends/{bob_id}/blend", headers=alice).json()
    titles = [t["title"] for t in blend["tracks"]]
    assert titles[0] == "Commun" and set(titles) == {"Commun", "A1", "A2", "B1", "B2"}
    assert blend["shared_tracks"] == 1 and blend["title"] == "Blend Alice + Bob"


def test_smart_playlists(client):
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = now - timedelta(days=200)
    client.post("/plays", headers=me, json={"plays": plays(["Oublié"] * 4, old) + plays(["Récent"] * 3, now)})
    lists = {p["id"]: p for p in client.get("/smart", headers=me, params={"tz": "UTC"}).json()}
    assert "forgotten" in lists and "on_repeat" in lists
    forgotten = client.get("/smart/forgotten", headers=me, params={"tz": "UTC"}).json()
    assert [t["title"] for t in forgotten] == ["Oublié"]
    assert client.get("/smart/nope", headers=me).status_code == 404


def test_web_page_and_stream_token(client):
    page = client.get("/web")
    assert page.status_code == 200 and "Sona" in page.text
    me = login(client, "alice")
    token = me["Authorization"].split()[1]
    # Sans jeton : refusé ; jeton dans l'adresse : accepté pour un flux audio
    # (balise <audio> du lecteur web), jamais ailleurs.
    assert client.get("/stream/deezer/1").status_code == 401
    assert client.get(f"/stream/deezer/1?token={token}").status_code != 401
    assert client.get(f"/me/playlists?token={token}").status_code == 401
