"""Import de bibliothèque : SoundCloud (playlists, likes), YouTube / YouTube
Music, rapport titre par titre (trouvés, à vérifier, introuvables),
corrections et resynchronisation — tout le réseau remplacé par des faux."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers import soundcloud as soundcloud_module
from app.providers import youtube
from app.providers.base import ExternalPlaylist, TrackInfo
from app.providers.link_detect import resolve_link
from app.providers.soundcloud import SoundcloudClient, SoundcloudError, track_from_api
from app.services import playlist_import
from app.services.playlist_import import detect_playlist_link, is_same_track, match_quality, origin_key

AUTH = {"Authorization": "Bearer test-token"}


def run(coro):
    return asyncio.run(coro)


# -- SoundCloud ------------------------------------------------------------------

HOME = '<html><script crossorigin src="https://a-v2.sndcdn.com/assets/0-abc.js"></script></html>'
SCRIPT = 'x={client_id:"ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",y:1}'


def sc_track(i, **extra):
    return {"id": i, "kind": "track", "title": f"Titre {i}", "duration": 200_000,
            "user": {"username": "Compte"}, "artwork_url": f"https://i1.sndcdn.com/a{i}-large.jpg", **extra}


def fake_soundcloud(api):
    """`api(path, params)` répond aux appels à api-v2 ; le site donne l'identifiant."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "soundcloud.com":
            return httpx.Response(200, text=HOME)
        if request.url.host == "a-v2.sndcdn.com":
            return httpx.Response(200, text=SCRIPT)
        status, body = api(request.url.path, dict(request.url.params))
        return httpx.Response(status, json=body)

    client = SoundcloudClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.calls = calls  # type: ignore[attr-defined]
    return client


def test_track_from_api_reads_artist_and_cleans_title():
    with_meta = track_from_api(sc_track(1, title="Titre (FREE DL)", publisher_metadata={"artist": "PNL", "isrc": "FR123", "album_title": "Deux frères"}))
    assert (with_meta.source, with_meta.source_id, with_meta.title, with_meta.artist) == ("soundcloud", "1", "Titre", "PNL")
    assert (with_meta.isrc, with_meta.album, with_meta.duration_seconds) == ("FR123", "Deux frères", 200)
    assert with_meta.cover_url == "https://i1.sndcdn.com/a1-t500x500.jpg"
    dashed = track_from_api(sc_track(2, title="Samuel Moriero - Call You [BUY FOR FREE DL]"))
    assert (dashed.title, dashed.artist) == ("Call You", "Samuel Moriero")
    plain = track_from_api(sc_track(3))
    assert plain.artist == "Compte"


def test_soundcloud_playlist_completes_partial_tracks_in_order():
    def api(path, params):
        assert params["client_id"] == "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        if path == "/resolve":
            return 200, {"kind": "playlist", "title": "Mon set", "track_count": 3,
                         "tracks": [sc_track(1), {"id": 2, "kind": "track"}, {"id": 3, "kind": "track"}]}
        assert path == "/tracks" and params["ids"] == "2,3"
        return 200, [sc_track(3), sc_track(2)]

    client = fake_soundcloud(api)
    playlist = run(client.get_playlist("https://soundcloud.com/a/sets/b"))
    assert playlist.name == "Mon set"
    assert [t.source_id for t in playlist.tracks] == ["1", "2", "3"]


def test_soundcloud_refreshes_a_stale_client_id():
    answers = iter([(401, {}), (200, sc_track(9))])
    client = fake_soundcloud(lambda path, params: next(answers))
    client._client_id = "perime"
    assert run(client.get_track("9")).title == "Titre 9"
    assert sum(1 for c in client.calls if c.url.host == "soundcloud.com") == 1


def test_soundcloud_likes_follow_pages_and_stop_at_the_limit(monkeypatch):
    monkeypatch.setattr(soundcloud_module, "MAX_TRACKS", 3)

    def api(path, params):
        if path == "/resolve":
            return 200, {"kind": "user", "id": 42, "username": "Jordi"}
        if path == "/users/42/likes" and "offset" not in params:
            return 200, {"collection": [{"track": sc_track(1)}, {"playlist": {}}, {"track": sc_track(2)}],
                         "next_href": "https://api-v2.soundcloud.com/users/42/likes?offset=2"}
        return 200, {"collection": [{"track": sc_track(3)}, {"track": sc_track(4)}], "next_href": "https://x/next"}

    likes = run(fake_soundcloud(api).get_likes("https://soundcloud.com/jordi/likes"))
    assert likes.name == "Likes de Jordi"
    assert [t.source_id for t in likes.tracks] == ["1", "2", "3"]
    assert "partiel" in likes.note


def test_soundcloud_not_found_and_not_a_playlist():
    with pytest.raises(SoundcloudError):
        run(fake_soundcloud(lambda p, q: (404, {})).get_playlist("https://soundcloud.com/a/sets/b"))
    with pytest.raises(SoundcloudError):
        run(fake_soundcloud(lambda p, q: (200, {"kind": "track"})).get_playlist("https://soundcloud.com/a/b"))


@pytest.mark.parametrize(("url", "kind", "ref"), [
    ("https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep?si=x", "playlist",
     "https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep"),
    ("https://m.soundcloud.com/jcv246/likes", "likes", "https://soundcloud.com/jcv246/likes"),
    ("https://soundcloud.com/coetxist/satisfaction-remix", "track", "https://soundcloud.com/coetxist/satisfaction-remix"),
    ("https://api.soundcloud.com/tracks/123", "track", "https://api.soundcloud.com/tracks/123"),
])
def test_soundcloud_links(url, kind, ref):
    detected = run(resolve_link(url))
    assert (detected.source, detected.kind, detected.ref) == ("soundcloud", kind, ref)


def test_soundcloud_site_pages_are_not_links():
    for url in ("https://soundcloud.com/discover", "https://soundcloud.com/jcv246", "https://soundcloud.com/jcv246/tracks"):
        assert run(resolve_link(url)) is None


def test_detect_playlist_link_new_sources():
    sc = run(detect_playlist_link("regarde https://soundcloud.com/a/sets/b"))
    assert (sc.source, sc.kind, sc.ref) == ("soundcloud", "playlist", "https://soundcloud.com/a/sets/b")
    likes = run(detect_playlist_link("https://soundcloud.com/a/likes"))
    assert (likes.source, likes.kind) == ("soundcloud", "likes")
    yt = run(detect_playlist_link("https://music.youtube.com/playlist?list=PLabc_123"))
    assert (yt.source, yt.ref) == ("youtube", "PLabc_123")
    with pytest.raises(playlist_import.PlaylistImportError, match="playlist"):
        run(detect_playlist_link("https://soundcloud.com/a/titre"))


# -- YouTube / YouTube Music ---------------------------------------------------

def test_split_video_title():
    assert youtube.split_video_title("Aya Nakamura - Djadja (Clip officiel)", "AyaNakamuraVEVO") == ("Djadja", "Aya Nakamura")
    assert youtube.split_video_title("Djadja", "Aya Nakamura - Topic") == ("Djadja", "Aya Nakamura")
    assert youtube.split_video_title("Blinding Lights [Official Video]", "The Weeknd") == ("Blinding Lights", "The Weeknd")


def test_youtube_music_playlist_for_import(monkeypatch):
    def fake(playlist_id, limit):
        assert playlist_id == "PL1"
        return {"title": "Été", "trackCount": 3, "thumbnails": [{"url": "https://t/1"}], "tracks": [
            {"videoId": "v1", "title": "Djadja", "artists": [{"name": "Aya Nakamura"}], "album": {"name": "Nakamura"},
             "duration_seconds": 171, "videoType": "MUSIC_VIDEO_TYPE_ATV"},
            {"videoId": "v2", "title": "PNL - Au DD (Clip officiel)", "artists": [{"name": "PNLVEVO"}],
             "duration_seconds": 240, "videoType": "MUSIC_VIDEO_TYPE_UGC"},
            {"videoId": "v3", "title": "Supprimée", "artists": [], "isAvailable": False},
        ]}

    monkeypatch.setattr(youtube, "_ytmusic_playlist_sync", fake)
    playlist = run(youtube.get_playlist_for_import("PL1"))
    assert playlist.name == "Été" and playlist.cover_url == "https://t/1"
    assert [(t.source_id, t.title, t.artist, t.album) for t in playlist.tracks] == [
        ("v1", "Djadja", "Aya Nakamura", "Nakamura"), ("v2", "Au DD", "PNL", None),
    ]


# -- Rapprochement -------------------------------------------------------------

def _t(title, artist="Ziak", duration=180, source="spotify", source_id="x", isrc=None):
    return TrackInfo(source, source_id, title, artist, None, None, duration, None, isrc=isrc)


def test_versions_must_match():
    assert not is_same_track(_t("Grabba - Live"), _t("Grabba", source="deezer"))
    assert not is_same_track(_t("Grabba"), _t("Grabba (Remix)", source="deezer"))
    assert is_same_track(_t("Grabba (Live)"), _t("Grabba - Live à Bercy", source="deezer"))
    assert is_same_track(_t("Grabba - Remastered 2011"), _t("Grabba", source="deezer"))


def test_match_quality():
    assert match_quality(_t("A", isrc="FR1", duration=100), _t("B", isrc="fr1", source="deezer")) == ("found", None)
    assert match_quality(_t("Grabba"), _t("Grabba", duration=182, source="deezer")) == ("found", None)
    status, reason = match_quality(_t("Grabba"), _t("Grabba", duration=186, source="deezer"))
    assert status == "uncertain" and "6 s" in reason
    status, reason = match_quality(_t("Grabba"), _t("Grabba Akimbo", source="deezer"))
    assert status == "uncertain" and "approchant" in reason


def test_origin_key():
    assert origin_key(_t("A", source_id="S1")) == "spotify:S1"
    assert origin_key(_t("Été (feat. X)", "Angèle, Y", source_id="")) == "meta:ete|angele"


# -- Parcours complet par l'API ------------------------------------------------

@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(playlist_import, "DEEZER_REQUESTS_PER_SECOND", 100_000)

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.app_state = main_module.app.state
        yield test_client


class CatalogDeezer:
    """Deezer qui connaît « Titre 1 » (même durée) et « Titre 2 » (6 s de plus)."""

    async def get_track_by_isrc(self, isrc):
        return None

    async def search_tracks(self, query, index=0, limit=25):
        if "Titre 1" in query:
            return [TrackInfo("deezer", "d1", "Titre 1", "Compte", "Album", None, 200, "https://c1")], 1
        if "Titre 2" in query:
            return [TrackInfo("deezer", "d2", "Titre 2", "Compte", "Album", None, 206, "https://c2")], 1
        return [], 0


class FakeSoundcloud:
    def __init__(self, rounds):
        self.rounds = rounds

    async def get_playlist(self, url):
        return ExternalPlaylist("Set", None, None, self.rounds.pop(0))

    async def get_likes(self, url):
        raise AssertionError("pas des likes")


def sc(i, title=None, duration=200):
    return TrackInfo("soundcloud", str(i), title or f"Titre {i}", "Compte", None, None, duration, None)


def wait_done(client, pid):
    for _ in range(100):
        detail = client.get(f"/me/playlists/{pid}", headers=AUTH).json()
        if detail["import_status"] != "importing":
            return detail
        client.portal.call(asyncio.sleep, 0.02)
    raise AssertionError("import jamais terminé")


def test_import_report_fix_and_sync(client):
    deps = client.app_state.deps
    deps.deezer = CatalogDeezer()
    first = [sc(1), sc(2), sc(3, "Exclu SoundCloud"), TrackInfo("spotify", "", "Rien", "Personne", None, None, 100, None)]
    second = [*first, sc(4), sc(1)]
    deps.soundcloud = FakeSoundcloud([first, second])

    pid = client.post("/me/playlists/import", headers=AUTH, json={"url": "https://soundcloud.com/a/sets/b"}).json()["id"]
    detail = wait_done(client, pid)
    assert detail["import_status"] == "done"
    assert (detail["import_missing"], detail["import_uncertain"]) == (1, 1)
    assert detail["origin_url"] == "https://soundcloud.com/a/sets/b"
    assert [e["track"]["source_id"] for e in detail["entries"]] == ["d1", "d2", "3"]

    report = client.get(f"/me/playlists/{pid}/import", headers=AUTH).json()
    assert report["counts"] == {"found": 2, "uncertain": 1, "missing": 1}
    by_title = {i["original"]["title"]: i for i in report["items"]}
    assert by_title["Titre 1"]["status"] == "found"
    assert by_title["Titre 2"]["status"] == "uncertain" and "6 s" in by_title["Titre 2"]["reason"]
    assert by_title["Exclu SoundCloud"]["matched"]["source"] == "soundcloud"
    assert by_title["Rien"]["status"] == "missing" and by_title["Rien"]["matched"] is None
    only_uncertain = client.get(f"/me/playlists/{pid}/import?status=uncertain", headers=AUTH).json()
    assert [i["original"]["title"] for i in only_uncertain["items"]] == ["Titre 2"]

    # Corrections : valider l'incertain, remplacer l'introuvable, retirer l'exclu.
    item2 = by_title["Titre 2"]["id"]
    accepted = client.post(f"/me/playlists/{pid}/import/{item2}", headers=AUTH, json={"action": "accept"}).json()
    assert (accepted["status"], accepted["fixed"]) == ("found", True)
    replacement = {"source": "deezer", "source_id": "d9", "title": "Rien du tout", "artist": "Personne"}
    replaced = client.post(f"/me/playlists/{pid}/import/{by_title['Rien']['id']}", headers=AUTH,
                           json={"action": "replace", "track": replacement}).json()
    assert replaced["matched"]["source_id"] == "d9" and replaced["entry_id"] is not None
    removed = client.post(f"/me/playlists/{pid}/import/{by_title['Exclu SoundCloud']['id']}", headers=AUTH,
                          json={"action": "remove"}).json()
    assert (removed["status"], removed["entry_id"]) == ("missing", None)
    assert client.post(f"/me/playlists/{pid}/import/{item2}", headers=AUTH, json={"action": "nope"}).status_code == 400
    assert client.post(f"/me/playlists/{pid}/import/999", headers=AUTH, json={"action": "accept"}).status_code == 400

    detail = client.get(f"/me/playlists/{pid}", headers=AUTH).json()
    assert [e["track"]["source_id"] for e in detail["entries"]] == ["d1", "d2", "d9"]
    assert (detail["import_missing"], detail["import_uncertain"]) == (1, 0)

    # Resynchronisation : seuls les nouveaux titres (Titre 4, et Titre 1 une
    # 2e fois) arrivent, à la fin ; les corrections restent.
    assert client.post(f"/me/playlists/{pid}/sync", headers=AUTH).status_code == 202
    detail = wait_done(client, pid)
    assert [e["track"]["source_id"] for e in detail["entries"]] == ["d1", "d2", "d9", "4", "d1"]
    assert detail["import_added"] == 2 and detail["import_total"] == 2
    report = client.get(f"/me/playlists/{pid}/import", headers=AUTH).json()
    assert report["counts"] == {"found": 5, "uncertain": 0, "missing": 1}


def test_link_fix_pins_the_audio_source_for_an_admin(client, monkeypatch):
    deps = client.app_state.deps
    deps.deezer = CatalogDeezer()
    deps.soundcloud = FakeSoundcloud([[sc(2)]])
    pid = client.post("/me/playlists/import", headers=AUTH, json={"url": "https://soundcloud.com/a/sets/b"}).json()["id"]
    wait_done(client, pid)
    item = client.get(f"/me/playlists/{pid}/import", headers=AUTH).json()["items"][0]
    assert item["status"] == "uncertain"

    fixed = client.post(f"/me/playlists/{pid}/import/{item['id']}", headers=AUTH,
                        json={"action": "link", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}).json()
    assert (fixed["status"], fixed["matched"]["source_id"]) == ("found", "d2")
    assert client.portal.call(deps.repo.stream_source_get, "deezer", "d2") == "dQw4w9WgXcQ"
    bad = client.post(f"/me/playlists/{pid}/import/{item['id']}", headers=AUTH, json={"action": "link", "url": "https://example.com"})
    assert bad.status_code == 400


def test_link_fix_replaces_the_track_for_a_member(monkeypatch, tmp_path):
    """Un membre (pas admin) qui colle un lien : le titre du lien prend la
    place dans sa playlist, la source du titre ne change pas pour les autres."""
    from app.db.database import Database
    from app.db.repository import ImportItem, Repository

    async def scenario():
        db = Database(tmp_path / "s.db")
        await db.connect()
        repo = Repository(db)
        pid = await repo.playlist_create(1, "P", origin="soundcloud", origin_url="https://soundcloud.com/a/sets/b")
        [entry] = await repo.playlist_add_tracks(pid, [sc(1)])
        await repo.import_items_add(pid, [ImportItem(None, pid, 0, "soundcloud:1", sc(1), "uncertain", "?", sc(1), entry)])
        item = (await repo.import_items(pid))[0]

        async def from_link(url):
            assert url == "https://youtu.be/abcdefghijk"
            return TrackInfo("youtube", "abcdefghijk", "Bon titre", "Bon artiste", None, None, 200, None)

        monkeypatch.setattr(playlist_import, "track_from_link", from_link)

        class Deps:
            is_admin = False

        Deps.repo = repo
        from app.api.routers.playlists import _fix_with_link

        playlist = await repo.playlist_get(1, pid)
        fixed = await _fix_with_link(Deps, playlist, item.id, "https://youtu.be/abcdefghijk")
        entries = await repo.playlist_tracks(pid)
        await db.close()
        return fixed, entries

    fixed, entries = asyncio.run(scenario())
    assert (fixed.status, fixed.matched.source_id, fixed.fixed) == ("found", "abcdefghijk", True)
    assert [(e.track.source, e.track.source_id) for e in entries] == [("youtube", "abcdefghijk")]


def test_soundcloud_tracks_are_playable_sources():
    from app.services.resolver import iter_audio_sources

    async def first():
        async for candidate in iter_audio_sources(sc(77)):
            return candidate

    candidate = asyncio.run(first())
    assert (candidate.video_id, candidate.platform) == ("soundcloud:77", "soundcloud")
