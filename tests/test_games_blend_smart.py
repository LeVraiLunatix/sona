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
    page = client.get("/web/")
    assert page.status_code == 200 and "Sona" in page.text
    assert client.get("/web", follow_redirects=False).status_code in (302, 307)
    assert "#/home" in client.get("/web/app.js").text or "viewHome" in client.get("/web/app.js").text
    assert client.get("/web/app.css").headers["content-type"].startswith("text/css")
    # Appli installable : manifeste, service worker et icônes.
    manifest = client.get("/web/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["display"] == "standalone"
    for icon in manifest.json()["icons"]:
        got = client.get(f"/web/{icon['src']}")
        assert got.status_code == 200 and got.headers["content-type"] == "image/png", icon["src"]
    assert "addEventListener(\"fetch\"" in client.get("/web/sw.js").text
    assert client.get("/web/icons/apple-touch-icon.png").headers["content-type"] == "image/png"
    me = login(client, "alice")
    token = me["Authorization"].split()[1]
    # Sans jeton : refusé ; jeton dans l'adresse : accepté pour un flux audio
    # (balise <audio> du lecteur web), jamais ailleurs.
    assert client.get("/stream/deezer/1").status_code == 401
    assert client.get(f"/stream/deezer/1?token={token}").status_code != 401
    assert client.get(f"/me/playlists?token={token}").status_code == 401


def test_web_page_calls_existing_routes(client):
    """Chaque appel fixe de la page web existe bien côté serveur (un
    `/me` au lieu de `/auth/me` bloquait la connexion sur une 404)."""
    import re

    page = client.get("/web/app.js").text
    me = login(client, "alice")
    paths = set(re.findall(r'api\("(/[^"?]*)', page))
    assert "/auth/me" in paths
    for path in paths:
        method = client.post if path in {"/plays", "/plays/now"} else client.get
        assert method(path, headers=me).status_code != 404, path


def test_dj_intro_script_and_fallback(client, monkeypatch):
    """Annonce écrite à partir des écoutes ; sans voix neuronale, le texte
    seul (l'app le lit avec une voix de l'iPhone)."""
    from app.services import dj_voice

    async def no_voice(self, text, voice="remy"):
        return None

    monkeypatch.setattr(dj_voice.Synthesizer, "speak", no_voice)
    me = login(client, "alice")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    client.post("/plays", headers=me, json={"plays": plays(["Tube"] * 9, now, artist="Star")})
    got = client.get("/dj/intro", headers=me, params={"title": "Tube", "artist": "Star"}).json()
    assert got["audio"] is None and "Tube" in got["text"]
    fresh = client.get("/dj/intro", headers=me, params={"title": "Inconnu (feat. X)", "artist": "Nouveau"}).json()
    assert "Nouveau" in fresh["text"] and "feat" not in fresh["text"]


def test_dj_voice_uses_cache(tmp_path):
    import asyncio

    from app.services import dj_voice

    synth = dj_voice.Synthesizer(tmp_path)
    path = synth._path("Bonjour", dj_voice.VOICES["remy"])
    path.write_bytes(b"mp3")
    assert asyncio.run(synth.speak("Bonjour", "remy")) == b"mp3"
