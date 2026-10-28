"""Paroles multi-sources : NetEase (yrc), Musixmatch (richsync), choix de la
meilleure source, correspondance, cache en base — tout le réseau remplacé
par de faux transports httpx."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.db.database import Database
from app.db.repository import Repository
from app.providers.lrclib import Lyrics, LyricsError, LyricsLine, LyricsWord
from app.providers.musixmatch import MusixmatchClient, parse_richsync
from app.providers.netease import NeteaseClient, NeteaseSong, lyrics_from_payload, parse_yrc
from app.services.lyrics import LyricsService, cache_key, detect_language, lyrics_from_dict, lyrics_to_dict, match

YRC = (
    '{"t":0,"c":[{"tx":"作曲: "},{"tx":"Pharrell Williams"}]}\n'
    "[4090,12150](4090,2430,0)吉(6520,2430,0)他(8950,2430,0)：(11380,2430,0)Nile (13810,2430,0)Rodgers\n"
    "[13230,2460](13230,500,0)Written (13730,500,0)by：(14230,500,0)Abel\n"
    "[31420,2670](31420,390,0)Like (31810,150,0)the (31960,630,0)legend\n"
    "[35980,2250](35980,300,0)All (36280,360,0)ends\n"
)


def run(coro):
    return asyncio.run(coro)


# -- NetEase -------------------------------------------------------------------

def test_parse_yrc_words_and_skips_credits():
    lines = parse_yrc(YRC)
    assert [line.text for line in lines] == ["Like the legend", "All ends"]
    first = lines[0]
    assert first.time == pytest.approx(31.42) and first.end == pytest.approx(34.09)
    assert [(w.time, w.text, w.end) for w in first.words] == [
        (pytest.approx(31.42), "Like ", pytest.approx(31.81)),
        (pytest.approx(31.81), "the ", pytest.approx(31.96)),
        (pytest.approx(31.96), "legend", pytest.approx(32.59)),
    ]


def test_netease_payload_variants():
    assert lyrics_from_payload({"nolyric": True}) is None
    assert lyrics_from_payload({"uncollected": True, "lrc": {"lyric": "[00:00.00]暂无歌词"}}) is None
    assert lyrics_from_payload({"lrc": {"lyric": "[00:00.00]纯音乐，请欣赏"}}).instrumental
    line_only = lyrics_from_payload({"lrc": {"lyric": "[00:01.00]作词 : X\n[00:05.00]Salut\n[00:09.00]"}, "yrc": {"lyric": ""}})
    assert line_only == Lyrics(synced=True, lines=[LyricsLine(5.0, "Salut")])
    worded = lyrics_from_payload({"lrc": {"lyric": "[00:31.42]Like the legend"}, "yrc": {"lyric": YRC}})
    assert worded.lines[0].words


def test_netease_client_search_and_lyrics():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search/get":
            assert request.url.params["s"] == "Daft Punk Get Lucky"
            return httpx.Response(200, json={"result": {"songs": [{
                "id": 26349642, "name": "Get Lucky", "duration": 369684,
                "artists": [{"name": "Daft Punk"}, {"name": "Pharrell Williams"}],
                "album": {"name": "Random Access Memories"},
            }]}})
        assert request.url.path == "/api/song/lyric/v1"
        return httpx.Response(200, json={"lrc": {"lyric": "[00:31.42]Like"}, "yrc": {"lyric": YRC}})

    client = NeteaseClient(httpx.AsyncClient(base_url="https://music.163.com/api", transport=httpx.MockTransport(handler)))
    songs = run(client.search("Get Lucky", "Daft Punk"))
    assert songs == [NeteaseSong(26349642, "Get Lucky", "Daft Punk, Pharrell Williams", "Random Access Memories", 369.684)]
    assert run(client.lyrics(26349642)).lines[0].text == "Like the legend"

    broken = NeteaseClient(httpx.AsyncClient(base_url="https://x", transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(LyricsError):
        run(broken.search("T", "A"))


# -- Musixmatch -----------------------------------------------------------------

def test_parse_richsync_glues_spaces_and_ends_words():
    body = json.dumps([{"ts": 10.0, "te": 12.0, "x": "Hello world", "l": [
        {"c": "Hello", "o": 0}, {"c": " ", "o": 0.4}, {"c": "world", "o": 0.5},
    ]}])
    [line] = parse_richsync(body)
    assert line.text == "Hello world" and line.end == 12.0
    assert [(w.time, w.text, w.end) for w in line.words] == [(10.0, "Hello ", 10.5), (10.5, "world", 12.0)]


def _mxm_message(body: dict, status: int = 200) -> dict:
    return {"message": {"header": {"status_code": status}, "body": body}}


def test_musixmatch_fake_anonymous_token_pauses_the_source():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_mxm_message({"user_token": "0" * 56}))

    client = MusixmatchClient(None, httpx.AsyncClient(base_url="https://m/ws/1.1", transport=httpx.MockTransport(handler)))
    with pytest.raises(LyricsError):
        run(client.find("T", "A", None, 100))
    assert not client.available
    assert run(client.find("T", "A", None, 100)) is None
    assert calls == ["/ws/1.1/token.get"]


def test_musixmatch_richsync_with_configured_token():
    rich = json.dumps([{"ts": 1.0, "te": 2.0, "x": "Salut toi", "l": [{"c": "Salut", "o": 0}, {"c": " ", "o": 0.3}, {"c": "toi", "o": 0.5}]}])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["usertoken"] == "vrai-jeton"
        if request.url.path.endswith("macro.subtitles.get"):
            return httpx.Response(200, json=_mxm_message({"macro_calls": {
                "matcher.track.get": _mxm_message({"track": {
                    "track_id": 7, "track_name": "Titre", "artist_name": "Artiste", "album_name": "Album",
                    "track_length": 200, "has_richsync": 1, "instrumental": 0,
                }}),
                "track.lyrics.get": _mxm_message({"lyrics": {"lyrics_body": "Salut toi\n\n******* This Lyrics is NOT for Commercial use", "lyrics_language": "fr"}}),
            }}))
        assert request.url.path.endswith("track.richsync.get")
        return httpx.Response(200, json=_mxm_message({"richsync": {"richsync_body": rich}}))

    client = MusixmatchClient("vrai-jeton", httpx.AsyncClient(base_url="https://m/ws/1.1", transport=httpx.MockTransport(handler)))
    meta, lyrics = run(client.find("Titre", "Artiste", "Album", 200))
    assert meta["title"] == "Titre" and meta["duration"] == 200.0 and meta["language"] == "fr"
    assert lyrics.synced and lyrics.lines[0].words[1].text == "toi"


# -- Correspondance et langue -------------------------------------------------

def test_match_tolerances():
    score, timing_ok = match("Djadja (feat. Maluma)", "Aya Nakamura, Maluma", None, 200, "Djadja", "Aya Nakamura", None, 201.5)
    assert score > 0.8 and timing_ok
    # 4 s d'écart : même titre, mais synchro inutilisable.
    assert match("Djadja", "Aya Nakamura", None, 200, "Djadja", "Aya Nakamura", None, 204)[1] is False
    # Autre chanson, autre artiste, autre enregistrement : refusés.
    assert match("Djadja", "Aya Nakamura", None, 200, "Copines", "Aya Nakamura", None, 200) is None
    assert match("Djadja", "Aya Nakamura", None, 200, "Djadja", "Inconnu", None, 200) is None
    assert match("Djadja", "Aya Nakamura", None, 200, "Djadja", "Aya Nakamura", None, 260) is None
    assert match("Get Lucky", "Daft Punk", None, 369, "NOKIA", "Drake", None, 241) is None
    # Autre version : refusée, sauf si c'est celle qu'on demande.
    assert match("Blinding Lights", "The Weeknd", None, 200, "Blinding Lights (Instrumental)", "The Weeknd", None, 200) is None
    assert match("Blinding Lights", "The Weeknd", None, 200, "Blinding Lights (Major Lazer Remix)", "The Weeknd", None, 200) is None
    assert match("Djadja - Remix", "Aya Nakamura", None, 200, "Djadja (Remix)", "Aya Nakamura", None, 200)
    assert match("Live Forever", "Oasis", None, 276, "Live Forever", "Oasis", None, 277)


def test_detect_language():
    fr = Lyrics(synced=False, lines=[LyricsLine(None, "Je suis là pour toi, c'est pas ma faute"), LyricsLine(None, "Et moi je pense que tu es dans mon cœur")])
    en = Lyrics(synced=False, lines=[LyricsLine(None, "I'm in love with you and the night is young"), LyricsLine(None, "Baby you are my everything, oh")])
    ja = Lyrics(synced=False, lines=[LyricsLine(None, "きみのことがすきです")])
    assert detect_language(fr) == "fr"
    assert detect_language(en) == "en"
    assert detect_language(ja) == "ja"
    assert detect_language(Lyrics(synced=False, lines=[LyricsLine(None, "la la la")])) is None


def test_lyrics_dict_roundtrip():
    lyrics = Lyrics(synced=True, lines=[LyricsLine(1.0, "Salut toi", words=[LyricsWord(1.0, "Salut ", 1.4), LyricsWord(1.4, "toi")], end=2.0)])
    assert lyrics_from_dict(json.loads(json.dumps(lyrics_to_dict(lyrics)))) == lyrics


def test_cache_key_ignores_features_and_remasters():
    assert cache_key("Djadja (feat. Maluma)", "Aya Nakamura, Maluma", 200) == cache_key("Djadja", "Aya Nakamura", 200)
    assert cache_key("Djadja", "Aya Nakamura", 200) != cache_key("Djadja", "Aya Nakamura", 230)


# -- Service -------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path):
    db = Database(tmp_path / "sona.db")
    run(db.connect())
    yield Repository(db)
    run(db.close())


LINE = Lyrics(synced=True, lines=[LyricsLine(1.0, "Bonjour"), LyricsLine(3.0, "Au revoir")])
WORD = Lyrics(synced=True, lines=[
    LyricsLine(1.0, "Bonjour", words=[LyricsWord(1.0, "Bonjour", 2.0)]),
    LyricsLine(3.0, "Au revoir", words=[LyricsWord(3.0, "Au ", 3.3), LyricsWord(3.3, "revoir", 4.0)]),
])


class FakeLrclib:
    def __init__(self, result=None, error=False):
        self.result, self.error, self.calls = result, error, 0

    async def get_lyrics(self, title, artist, album=None, duration=None):
        self.calls += 1
        if self.error:
            raise LyricsError("LRCLIB injoignable")
        return self.result


class FakeNetease:
    def __init__(self, songs, lyrics, error=False):
        self.songs, self._lyrics, self.error, self.calls = songs, lyrics, error, 0

    async def search(self, title, artist):
        self.calls += 1
        if self.error:
            raise LyricsError("NetEase injoignable")
        return self.songs

    async def lyrics(self, song_id):
        return self._lyrics.get(song_id)


class FakeMusixmatch:
    def __init__(self, found=None):
        self.found = found

    async def find(self, title, artist, album, duration):
        return self.found


def test_word_level_beats_line_level(repo):
    netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 200.5)], {1: WORD})
    service = LyricsService(repo, FakeLrclib(LINE), netease)
    result = run(service.get("Titre", "Artiste", None, 200))
    assert (result.source, result.sync) == ("netease", "word")


def test_line_level_prefers_lrclib_and_wrong_duration_loses_sync(repo):
    # NetEase connaît une version 20 s plus longue : texte gardé, synchro non.
    netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 220)], {1: WORD})
    service = LyricsService(repo, FakeLrclib(LINE), netease)
    result = run(service.get("Titre", "Artiste", None, 200))
    assert (result.source, result.sync) == ("lrclib", "line")

    alone = LyricsService(repo, FakeLrclib(None), netease)
    plain = run(alone.get("Titre", "Artiste", None, 200, refresh=True))
    assert (plain.source, plain.sync) == ("netease", "none")
    assert plain.lyrics.lines[1].time is None


def test_close_version_keeps_approximate_timing_but_exact_one_wins(repo):
    # 10 s d'écart : le mot par mot de NetEase reste, marqué approximatif.
    netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 210)], {1: WORD})
    only = LyricsService(repo, FakeLrclib(None), netease)
    approx = run(only.get("Titre", "Artiste", None, 200))
    assert (approx.source, approx.sync, approx.lyrics.approximate) == ("netease", "word", True)
    assert approx.lyrics.lines[1].words

    # Une synchro exacte de LRCLIB (ligne par ligne) passe avant l'approximative.
    both = LyricsService(repo, FakeLrclib(LINE), netease)
    exact = run(both.get("Titre", "Artiste", None, 200, refresh=True))
    assert (exact.source, exact.sync, exact.lyrics.approximate) == ("lrclib", "line", False)

    # L'indication survit au cache (sérialisation).
    assert lyrics_from_dict(lyrics_to_dict(approx.lyrics)).approximate
    assert not lyrics_from_dict(lyrics_to_dict(exact.lyrics)).approximate


def test_musixmatch_wrong_song_is_rejected(repo):
    nokia = ({"title": "NOKIA", "artist": "Drake", "album": None, "duration": 241.0}, WORD)
    service = LyricsService(repo, FakeLrclib(LINE), None, FakeMusixmatch(nokia))
    assert run(service.get("Get Lucky", "Daft Punk", None, 369)).source == "lrclib"


def test_results_and_absences_are_cached(repo):
    lrclib = FakeLrclib(LINE)
    service = LyricsService(repo, lrclib)
    first = run(service.get("Titre", "Artiste", "Album", 200))
    again = run(service.get("Titre (feat. X)", "Artiste", None, 200))
    assert lrclib.calls == 1
    assert again.lyrics == first.lyrics and again.source == "lrclib"

    missing = FakeLrclib(None)
    service = LyricsService(repo, missing)
    assert run(service.get("Rien", "Personne", None, 100)) is None
    assert run(service.get("Rien", "Personne", None, 100)) is None
    assert missing.calls == 1
    # « Chercher encore » ignore le cache.
    assert run(service.get("Rien", "Personne", None, 100, refresh=True)) is None
    assert missing.calls == 2


def test_errors_everywhere_raise_and_are_not_cached(repo):
    lrclib = FakeLrclib(error=True)
    netease = FakeNetease([], {}, error=True)
    service = LyricsService(repo, lrclib, netease)
    with pytest.raises(LyricsError):
        run(service.get("Titre", "Artiste", None, 200))
    lrclib.error = False
    lrclib.result = LINE
    assert run(service.get("Titre", "Artiste", None, 200)).source == "lrclib"


def test_header_line_is_removed(repo):
    headed = Lyrics(synced=True, lines=[LyricsLine(0.5, "Artiste - Titre"), *WORD.lines])
    netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 200)], {1: headed})
    result = run(LyricsService(repo, FakeLrclib(None), netease).get("Titre", "Artiste", None, 200))
    assert [line.text for line in result.lyrics.lines] == ["Bonjour", "Au revoir"]


def test_one_source_down_still_answers(repo):
    service = LyricsService(repo, FakeLrclib(LINE), FakeNetease([], {}, error=True))
    assert run(service.get("Titre", "Artiste", None, 200)).source == "lrclib"


def test_concurrent_requests_share_one_lookup(repo):
    class SlowLrclib(FakeLrclib):
        async def get_lyrics(self, *args, **kwargs):
            await asyncio.sleep(0.05)
            return await super().get_lyrics(*args, **kwargs)

    lrclib = SlowLrclib(LINE)
    service = LyricsService(repo, lrclib)

    async def both():
        return await asyncio.gather(service.get("Titre", "Artiste", None, 200), service.get("Titre", "Artiste", None, 200))

    a, b = run(both())
    assert a.lyrics == b.lyrics == LINE and lrclib.calls == 1


def test_endpoint_reports_source_sync_and_language(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    import app.api.main as main_module

    with TestClient(main_module.app) as client:
        deps = main_module.app.state.deps
        deps.lyrics._netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 200)], {1: WORD})

        async def nothing(*args, **kwargs):
            return None

        deps.lrclib.get_lyrics = nothing
        got = client.get("/lyrics", headers={"Authorization": "Bearer test-token"}, params={"title": "Titre", "artist": "Artiste", "duration": 200})
        assert got.status_code == 200
        body = got.json()
        assert (body["source"], body["sync"], body["synced"]) == ("netease", "word", True)
        assert body["lines"][1]["words"][0] == {"time": 3.0, "text": "Au ", "end": 3.3}


# -- Recherche automatique ---------------------------------------------------

def _expire(repo, key):
    async def run_():
        await repo._db.conn.execute("UPDATE lyrics_cache SET expires_at='2000-01-01T00:00:00+00:00' WHERE cache_key=?", (key,))
        await repo._db.conn.commit()

    run(run_())


def test_absence_is_searched_again_by_itself(repo):
    lrclib = FakeLrclib(None)
    service = LyricsService(repo, lrclib)
    assert run(service.get("Titre", "Artiste", None, 200)) is None
    assert run(service.get("Titre", "Artiste", None, 200)) is None
    assert lrclib.calls == 1
    # Le délai passé (30 min), la demande suivante cherche de nouveau.
    _expire(repo, cache_key("Titre", "Artiste", 200))
    lrclib.result = LINE
    assert run(service.get("Titre", "Artiste", None, 200)).source == "lrclib"
    assert lrclib.calls == 2


def test_stale_lyrics_stay_while_better_ones_are_searched(repo):
    netease = FakeNetease([NeteaseSong(1, "Titre", "Artiste", None, 200)], {})
    service = LyricsService(repo, FakeLrclib(LINE), netease)
    assert run(service.get("Titre", "Artiste", None, 200)).sync == "line"

    # Périmées : affichées tout de suite, et NetEase a maintenant le mot par mot.
    _expire(repo, cache_key("Titre", "Artiste", 200))
    netease._lyrics = {1: WORD}

    async def twice():
        first = await service.get("Titre", "Artiste", None, 200)
        await asyncio.gather(*service._upgrades.values())
        return first, await service.get("Titre", "Artiste", None, 200)

    first, then = run(twice())
    assert first.sync == "line" and (then.sync, then.source) == ("word", "netease")


def test_slow_source_does_not_delay_the_answer_and_upgrades_the_cache(repo, monkeypatch):
    import app.services.lyrics as lyrics_module

    monkeypatch.setattr(lyrics_module, "FAST_GRACE", 0.05)

    class SlowNetease(FakeNetease):
        async def search(self, title, artist):
            await asyncio.sleep(0.4)
            return await super().search(title, artist)

    netease = SlowNetease([NeteaseSong(1, "Titre", "Artiste", None, 200)], {1: WORD})
    service = LyricsService(repo, FakeLrclib(LINE), netease)

    async def scenario():
        started = asyncio.get_running_loop().time()
        first = await service.get("Titre", "Artiste", None, 200)
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.gather(*service._background)
        return first, elapsed, await service.get("Titre", "Artiste", None, 200)

    first, elapsed, then = run(scenario())
    # Réponse immédiate avec LRCLIB (ligne), sans attendre NetEase ; le cache
    # a ensuite reçu le mot par mot.
    assert first.sync == "line" and elapsed < 0.3
    assert (then.sync, then.source) == ("word", "netease")


def test_upgrade_never_replaces_lyrics_with_worse(repo):
    lrclib = FakeLrclib(LINE)
    service = LyricsService(repo, lrclib)
    run(service.get("Titre", "Artiste", None, 200))
    _expire(repo, cache_key("Titre", "Artiste", 200))
    lrclib.result = None  # plus rien à la source

    async def twice():
        await service.get("Titre", "Artiste", None, 200)
        await asyncio.gather(*service._upgrades.values())
        return await service.get("Titre", "Artiste", None, 200)

    assert run(twice()).lyrics == LINE


def test_second_pass_with_the_bare_title():
    from app.services.lyrics import base_title

    assert base_title('Song (From "Film") - 2019 Mix') == "Song"
    assert base_title("Djadja") == "Djadja"


def test_bare_title_finds_lyrics_the_full_title_missed(repo):
    class PickyLrclib(FakeLrclib):
        async def get_lyrics(self, title, artist, album=None, duration=None):
            self.calls += 1
            return LINE if title == "Song" else None

    lrclib = PickyLrclib()
    result = run(LyricsService(repo, lrclib).get('Song (From "Film")', "Artiste", None, 200))
    assert result.lyrics == LINE and lrclib.calls == 2
