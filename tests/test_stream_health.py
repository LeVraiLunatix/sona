"""Lecture qui ne tombe pas en panne : santé, repli sur d'autres sources,
cookies renvoyés depuis l'app, mise à jour de yt-dlp avec retour arrière."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers import health, stream
from app.providers.base import TrackInfo
from app.services import stream_health, youtube_session, ytdlp_updater
from app.services.audio_match import Verdict
from app.services.downloader import DownloadError
from app.services.resolver import Candidate

AUTH = {"Authorization": "Bearer test-token"}
TRACK = TrackInfo("deezer", "5", "Titre", "Artiste", None, None, 180, None)
COOKIES = "# Netscape HTTP Cookie File\n" + "\t".join(
    [".youtube.com", "TRUE", "/", "TRUE", "1999999999", "SID", "valeur"]
) + "\n#HttpOnly_" + "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1999999999", "HSID", "x"]) + "\n"


def test_classify_and_states():
    assert stream_health.classify("Sign in to confirm you're not a bot") == "cookies"
    assert stream_health.classify("Requested format is not available") == "ytdlp"
    assert stream_health.classify("HTTP Error 403: Forbidden") == "network"
    assert stream_health.classify("Video unavailable") == "other"
    now = 10_000.0
    for _ in range(3):
        stream_health.record(True, now=now)
    assert stream_health.status(now)["state"] == "ok"
    for _ in range(3):
        stream_health.record(False, "cookies", now=now)
    down = stream_health.status(now)
    assert down["state"] == "down" and down["cause"] == "cookies" and "cookies" in down["advice"].lower()
    assert "panne" in stream_health.alert_for("ok", down)
    # Des titres introuvables ne sont pas une panne.
    stream_health.reset()
    for _ in range(5):
        stream_health.record(False, "other", now=now)
    assert stream_health.status(now)["state"] == "ok"
    # Tout est oublié au bout d'une demi-heure.
    stream_health.record(False, "ytdlp", now=now)
    assert stream_health.status(now + 3600)["recent_failures"] == 0


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("STREAM_CACHE_DIR", str(tmp_path / "stream"))
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(tmp_path / "secret" / "cookies.txt"))
    stream._failures.clear()

    async def no_live(deps, source, source_id, key):
        return None

    monkeypatch.setattr(stream, "_live_source", no_live)
    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        yield test_client
    stream._failures.clear()


def test_youtube_down_falls_back_to_soundcloud(client, tmp_path, monkeypatch):
    youtube = Candidate(video_id="yt1", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                        cover_url=None, is_song=True)
    youtube2 = Candidate(video_id="yt2", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                         cover_url=None, is_song=True)
    soundcloud = Candidate(video_id="soundcloud:9", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                           cover_url=None, is_song=False, platform="soundcloud", url="https://soundcloud.com/a/titre")
    tried = []

    async def track_for(deps, source, source_id):
        return TRACK

    async def same(deezer, track):
        return track

    async def sources(track, cookies, excluded, preferred, found=None):
        for candidate in (youtube, youtube2, soundcloud):
            yield candidate

    async def download(settings, url, track, quality, fmt):
        tried.append(url)
        if "youtube.com" in url:
            raise DownloadError("Téléchargement audio impossible.", bot_wall=True)
        path = tmp_path / "work" / "titre.m4a"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"audio")
        return path

    async def verify(track, path, ffmpeg):
        return Verdict(0.05)

    monkeypatch.setattr(stream, "_track_for", track_for)
    monkeypatch.setattr(stream, "complete_preview", same)
    monkeypatch.setattr(stream, "iter_audio_sources", sources)
    monkeypatch.setattr(stream, "download_and_tag", download)
    monkeypatch.setattr(stream, "verify_recording", verify)
    ready = client.post("/stream/deezer/5/prepare", headers=AUTH)
    assert ready.status_code == 200, ready.text
    # Un seul essai YouTube (les autres vidéos YouTube sont sautées), puis SoundCloud.
    assert tried == ["https://www.youtube.com/watch?v=yt1", "https://soundcloud.com/a/titre"]
    state = stream_health.status()
    assert state["recent_ok"] == 1 and state["recent_failures"] == 1
    assert client.get("/health").json()["streaming"] == "ok"


def test_lost_known_source_does_not_rule_out_youtube(client, tmp_path, monkeypatch):
    """La vidéo mémorisée pour un titre a disparu : les autres vidéos YouTube
    restent essayées, YouTube n'est pas en panne pour autant."""
    known = Candidate(video_id="old", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                      cover_url=None, is_song=True)
    other = Candidate(video_id="yt2", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                      cover_url=None, is_song=True)
    tried = []

    async def track_for(deps, source, source_id):
        return TRACK

    async def same(deezer, track):
        return track

    async def preferred(self, source, source_id):
        return "old"

    async def sources(track, cookies, excluded, preferred, found=None):
        assert preferred == "old"
        for candidate in (known, other):
            yield candidate

    async def download(settings, url, track, quality, fmt):
        tried.append(url)
        if url.endswith("=old"):
            raise DownloadError("Téléchargement audio impossible.")
        path = tmp_path / "work" / "titre.m4a"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"audio")
        return path

    async def verify(track, path, ffmpeg):
        return Verdict(0.05)

    from app.db.repository import Repository

    monkeypatch.setattr(Repository, "stream_source_get", preferred)
    monkeypatch.setattr(stream, "_track_for", track_for)
    monkeypatch.setattr(stream, "complete_preview", same)
    monkeypatch.setattr(stream, "iter_audio_sources", sources)
    monkeypatch.setattr(stream, "download_and_tag", download)
    monkeypatch.setattr(stream, "verify_recording", verify)
    ready = client.post("/stream/deezer/5/prepare", headers=AUTH)
    assert ready.status_code == 200, ready.text
    assert tried == ["https://www.youtube.com/watch?v=old", "https://www.youtube.com/watch?v=yt2"]


def test_diagnose_reports_why_each_source_was_rejected(client, tmp_path, monkeypatch):
    """« Diagnostic de lecture » : un titre qui ne se lance pas dit pourquoi,
    sans lire les journaux du serveur — même juste après un échec."""
    snippet = Candidate(video_id="soundcloud:7", title="Titre", artist="Artiste", album=None, duration_seconds=180,
                        cover_url=None, is_song=False, platform="soundcloud", url="https://soundcloud.com/a/titre")
    instru = Candidate(video_id="yt-instru", title="Artiste - Titre (Instrumental)", artist="Beats", album=None,
                       duration_seconds=180, cover_url=None, is_song=False)
    downloads = []

    async def track_for(deps, source, source_id):
        return TRACK

    async def same(deezer, track):
        return track

    async def sources(track, cookies, excluded, preferred, found=None):
        found.extend([snippet, instru])
        yield snippet

    async def download(settings, url, track, quality, fmt):
        downloads.append(url)
        path = tmp_path / "work" / "titre.m4a"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"audio")
        return path

    async def verify(track, path, ffmpeg):
        return Verdict(1.0, "fichier de 30 s au lieu de 180 s")

    monkeypatch.setattr(stream, "_track_for", track_for)
    monkeypatch.setattr(stream, "complete_preview", same)
    monkeypatch.setattr(stream, "iter_audio_sources", sources)
    monkeypatch.setattr(stream, "download_and_tag", download)
    monkeypatch.setattr(stream, "verify_recording", verify)
    assert client.post("/stream/deezer/5/prepare", headers=AUTH).status_code == 404

    got = client.post("/admin/diagnose/deezer/5", headers=AUTH)
    assert got.status_code == 200, got.text
    report = got.json()
    assert len(downloads) == 2  # l'échec récent n'empêche pas le diagnostic de réessayer
    assert report["ready"] is False
    assert report["result"] == "Aucune version fidèle de ce morceau n'a été trouvée."
    assert report["track"]["title"] == "Titre"
    assert report["tried"] == [{
        "id": "soundcloud:7", "platform": "soundcloud", "title": "Titre", "artist": "Artiste",
        "duration_seconds": 180, "outcome": "écartée : fichier de 30 s au lieu de 180 s",
    }]
    reasons = {r["id"]: r["rejected"] for r in report["found"]}
    assert reasons == {"soundcloud:7": None, "yt-instru": "version dérivée (instrumental)"}
    assert client.post("/admin/diagnose/deezer/5").status_code == 401


def test_only_version_flagged_as_wrong_is_explained_and_can_be_restored(client, tmp_path, monkeypatch):
    """Cas réel : « Frontières » de PNL. La seule version trouvée avait été
    signalée « Mauvaise version ? » : plus aucune source n'était essayée, et
    l'app disait juste « Titre introuvable ». Le diagnostic le montre, et
    l'admin peut réautoriser la source."""
    from app.services import resolver

    repost = Candidate(video_id="sanji", title="PNL - Frontière - [ Officiel Album Deux Frères ]", artist="SANJI",
                       album=None, duration_seconds=180, cover_url=None, is_song=False)
    ref = TrackInfo("deezer", "5", "Frontières", "PNL", "Deux frères", None, 180, None)
    downloads = []

    async def track_for(deps, source, source_id):
        return ref

    async def same(deezer, track):
        return track

    async def download(settings, url, track, quality, fmt):
        downloads.append(url)
        path = tmp_path / "work" / "titre.m4a"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"audio")
        return path

    async def verify(track, path, ffmpeg):
        return Verdict(0.05)

    monkeypatch.setattr(resolver, "_search_ytmusic_sync", lambda queries: [repost])
    monkeypatch.setattr(resolver, "_search_soundcloud_sync", lambda query: [])
    monkeypatch.setattr(resolver, "_search_ytdlp_sync", lambda query, cookies: [])
    monkeypatch.setattr(stream, "_track_for", track_for)
    monkeypatch.setattr(stream, "complete_preview", same)
    monkeypatch.setattr(stream, "download_and_tag", download)
    monkeypatch.setattr(stream, "verify_recording", verify)
    repo = client.app.state.deps.repo
    client.portal.call(repo.reject_source, "deezer", "5", "sanji")

    failed = client.post("/stream/deezer/5/prepare", headers=AUTH)
    assert failed.status_code == 404
    assert "Mauvaise version" in failed.json()["detail"]
    report = client.post("/admin/diagnose/deezer/5", headers=AUTH).json()
    assert report["excluded"] == 1 and report["tried"] == []
    assert report["found"][0]["rejected"] == "écartée par « Mauvaise version ? »"
    assert downloads == []

    assert client.post("/admin/diagnose/deezer/5/unreject", headers=AUTH).json() == {"unrejected": 1}
    report = client.post("/admin/diagnose/deezer/5", headers=AUTH).json()
    assert report["ready"] is True and report["excluded"] == 0
    assert downloads == ["https://www.youtube.com/watch?v=sanji"]


def test_cookies_upload_from_the_app(client, tmp_path, monkeypatch):
    checked = []

    async def check(path, reason):
        checked.append(Path(path))
        return True

    monkeypatch.setattr(youtube_session, "check_session", check)
    bad = client.post("/admin/youtube-cookies", headers=AUTH, json={"content": "pas un fichier de cookies"})
    assert bad.status_code == 422
    got = client.post("/admin/youtube-cookies", headers=AUTH, json={"content": COOKIES})
    assert got.status_code == 200, got.text
    assert got.json()["cookies"] == 2 and got.json()["logged_in"] is True
    written = tmp_path / "secret" / "cookies.txt"
    assert written.read_text() == COOKIES and oct(written.stat().st_mode & 0o777) == "0o600"
    assert checked == [written]
    status = client.get("/admin/streaming", headers=AUTH).json()
    assert status["cookies"]["present"] and status["health"]["state"] == "ok" and status["ytdlp"]["version"]


def test_admin_endpoints_need_an_admin(client):
    assert client.get("/admin/streaming").status_code == 401


def test_validate_cookies_counts_youtube_ones():
    assert health.validate_cookies(COOKIES) == 2
    with pytest.raises(ValueError):
        health.validate_cookies("\t".join([".example.com", "TRUE", "/", "TRUE", "0", "a", "b"]))


def fake_runner(versions, tests, installs):
    return {
        "version": lambda: versions.pop(0),
        "selftest": lambda: tests.pop(0),
        "install": lambda spec: installs.append(spec) or True,
        "restart": lambda: installs.append("restart"),
    }


def test_updater_updates_then_rolls_back_a_broken_version(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_updater, "STATE_FILE", tmp_path / "state.json")
    installs = []
    ok = ytdlp_updater.update(runner=fake_runner(["1.0", "2.0"], [(True, "ok"), (True, "ok")], installs))
    assert ok["result"] == "updated" and ok["version"] == "2.0" and installs[-1] == "restart"

    installs.clear()
    broken = ytdlp_updater.update(runner=fake_runner(["2.0", "3.0"], [(True, "ok"), (False, "nsig")], installs))
    assert broken["result"] == "rolled_back" and broken["version"] == "2.0"
    assert installs == ["yt-dlp[default,deno]", "yt-dlp[default,deno]==2.0"]
    assert ytdlp_updater.read_state()["result"] == "rolled_back"

    same = ytdlp_updater.update(runner=fake_runner(["2.0", "2.0"], [(True, "ok")], []))
    assert same["result"] == "up_to_date"
