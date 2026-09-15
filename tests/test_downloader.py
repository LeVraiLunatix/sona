import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp

from app.config import Settings
from app.logging_config import ytdlp_logger
from app.providers.base import TrackInfo
from app.services import downloader
from app.services.downloader import (
    DownloadError,
    _build_opts,
    _download_sync,
    _find_output,
    _format_selector_for,
    _sanitize_filename,
    cleanup_download,
    download_and_tag,
)


def test_sanitize_removes_filesystem_hostile_characters():
    assert _sanitize_filename('AC/DC - Back: "Black"?') == "ACDC - Back Black"


def test_sanitize_never_returns_an_empty_name():
    assert _sanitize_filename("///") == "sona_track"
    assert _sanitize_filename("...") == "sona_track"


def test_find_output_handles_brackets_in_title(tmp_path):
    """Les crochets sont fréquents dans les titres YouTube et sont des
    métacaractères de glob : sans échappement, le fichier reste introuvable
    et le morceau paraît indisponible."""
    produced = tmp_path / "Artiste - Titre [Official Video].m4a"
    produced.write_bytes(b"audio")
    expected = tmp_path / "Artiste - Titre [Official Video].mp3"
    assert _find_output(expected) == produced


def test_find_output_prefers_the_requested_codec(tmp_path):
    """yt-dlp laisse le flux brut à côté du fichier converti : c'est le format
    demandé qui doit être envoyé, même si le brut est plus récent sur disque."""
    converted = tmp_path / "Artiste - Titre.m4a"
    converted.write_bytes(b"audio")
    raw = tmp_path / "Artiste - Titre.webm"
    raw.write_bytes(b"flux brut")
    os.utime(raw, (time.time() + 10, time.time() + 10))

    # Nom attendu différent (yt-dlp a nettoyé le titre) : la découverte passe
    # par le balayage du dossier de travail.
    assert _find_output(tmp_path / "Artiste - Titre (original).m4a") == converted


def test_find_output_ignores_partial_downloads(tmp_path):
    (tmp_path / "morceau.m4a.part").write_bytes(b"incomplet")
    with pytest.raises(DownloadError):
        _find_output(tmp_path / "morceau.m4a")


def test_cleanup_removes_the_whole_work_directory(tmp_path):
    work_dir = tmp_path / "sona-dl-abc123"
    work_dir.mkdir()
    audio = work_dir / "morceau.m4a"
    audio.write_bytes(b"audio")
    (work_dir / "morceau.webm").write_bytes(b"flux brut")

    cleanup_download(audio)
    assert not work_dir.exists()


def test_cleanup_leaves_other_directories_alone(tmp_path):
    audio = tmp_path / "morceau.m4a"
    audio.write_bytes(b"audio")
    cleanup_download(audio)
    assert not audio.exists()
    assert tmp_path.exists()


def test_quality_setting_changes_the_requested_stream():
    assert "abr<=128" in _format_selector_for("standard")
    assert "abr<=128" not in _format_selector_for("best")
    # Dernier recours : on accepte n'importe quel flux plutôt que d'échouer.
    assert _format_selector_for("standard", broad=True) == "bestaudio/best/bestaudio*"


def test_find_output_returns_the_expected_file_when_present(tmp_path):
    expected = tmp_path / "morceau.m4a"
    expected.write_bytes(b"audio")
    assert _find_output(expected) == expected


def test_find_output_without_any_audio_raises(tmp_path):
    assert isinstance(tmp_path, Path)
    with pytest.raises(DownloadError):
        _find_output(tmp_path / "absent.m4a")


BOT_WALL = (
    "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. "
    "Use --cookies-from-browser or --cookies for the authentication."
)
TRACK = TrackInfo(
    source="deezer",
    source_id="1",
    title="Titre",
    artist="Artiste",
    album=None,
    year=None,
    duration_seconds=None,
    cover_url=None,
)


def _failing_attempts(monkeypatch, messages):
    """Chaque tentative de la cascade échoue avec le message suivant."""
    remaining = list(messages)

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError(remaining.pop(0))

    monkeypatch.setattr(downloader, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(downloader, "time", SimpleNamespace(sleep=lambda _seconds: None))


def _settings(tmp_path, cookies_file):
    return Settings(
        bot_token="test",
        allowed_user_ids=frozenset(),
        spotify_client_id=None,
        spotify_client_secret=None,
        ffmpeg_path="ffmpeg",
        database_path=tmp_path / "sona.db",
        youtube_cookies_file=cookies_file,
        downloads_dir=tmp_path,
    )


def test_ytdlp_warnings_go_to_the_logger_instead_of_being_silenced():
    """`no_warnings` masquait aussi « cookies are no longer valid »."""
    opts = _build_opts(downloader._ATTEMPTS[0], "out.%(ext)s", "ffmpeg", "best", "m4a", Path("cookies.txt"))
    assert "no_warnings" not in opts
    assert opts["logger"] is ytdlp_logger
    assert not opts.get("nocheckcertificate")


def test_cascade_entirely_blocked_by_the_bot_wall_is_flagged(monkeypatch):
    _failing_attempts(monkeypatch, [BOT_WALL] * len(downloader._ATTEMPTS))
    with pytest.raises(DownloadError) as caught:
        _download_sync("abc", "out.%(ext)s", "ffmpeg", "best", "auto", Path("cookies.txt"))
    assert caught.value.bot_wall


def test_cascade_with_another_failure_is_not_flagged(monkeypatch):
    messages = [BOT_WALL] * (len(downloader._ATTEMPTS) - 1) + ["ERROR: Requested format is not available"]
    _failing_attempts(monkeypatch, messages)
    with pytest.raises(DownloadError) as caught:
        _download_sync("abc", "out.%(ext)s", "ffmpeg", "best", "auto", Path("cookies.txt"))
    assert not caught.value.bot_wall


def test_bot_wall_triggers_a_background_session_check(monkeypatch, tmp_path):
    cookies = tmp_path / "cookies.txt"
    checks = []

    def blocked(*_args):
        raise DownloadError("Téléchargement audio impossible.", bot_wall=True)

    monkeypatch.setattr(downloader, "_download_sync", blocked)
    monkeypatch.setattr(
        downloader.youtube_session, "schedule_session_check", lambda path, reason: checks.append(path)
    )

    with pytest.raises(DownloadError):
        asyncio.run(download_and_tag(_settings(tmp_path, cookies), "abc", TRACK))
    assert checks == [cookies]
    assert not list(tmp_path.glob("sona-dl-*"))


def test_ordinary_failure_does_not_trigger_a_session_check(monkeypatch, tmp_path):
    checks = []

    def broken(*_args):
        raise DownloadError("Téléchargement audio impossible.")

    monkeypatch.setattr(downloader, "_download_sync", broken)
    monkeypatch.setattr(
        downloader.youtube_session, "schedule_session_check", lambda path, reason: checks.append(path)
    )

    with pytest.raises(DownloadError):
        asyncio.run(download_and_tag(_settings(tmp_path, tmp_path / "cookies.txt"), "abc", TRACK))
    assert checks == []


def _recording_ytdlp(monkeypatch, message):
    """yt-dlp factice qui échoue toujours et garde les options de chaque tentative."""
    seen = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            seen.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError(message)

    monkeypatch.setattr(downloader, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(downloader, "time", SimpleNamespace(sleep=lambda _seconds: None))
    return seen


def test_soundcloud_is_downloaded_once_without_youtube_cookies(monkeypatch):
    """Ni mur anti-bot ni clients à alterner hors YouTube : une seule
    tentative, et les cookies YouTube ne partent pas chez SoundCloud."""
    seen = _recording_ytdlp(monkeypatch, "ERROR: [soundcloud] 1: This video is DRM protected")
    with pytest.raises(DownloadError) as caught:
        _download_sync(
            "https://soundcloud.com/exemple/titre", "out.%(ext)s", "ffmpeg", "best", "auto", Path("cookies.txt")
        )
    assert len(seen) == 1
    assert "cookiefile" not in seen[0]
    assert not caught.value.bot_wall


def test_download_prepares_the_thumbnail_and_embeds_only_jpeg_or_png(monkeypatch, tmp_path):
    """La vignette de la bulle Telegram se fait à partir de n'importe quelle
    image ; la pochette n'est intégrée au fichier que si c'est du JPEG ou du PNG."""
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 "

    def fake_download(source, out_template, *_args):
        audio = Path(out_template.replace("%(ext)s", "m4a"))
        audio.write_bytes(b"audio")
        return audio

    async def fetch_cover(url):
        return webp

    thumbnails, embedded = [], []
    monkeypatch.setattr(downloader, "_download_sync", fake_download)
    monkeypatch.setattr(downloader, "_fetch_cover_bytes", fetch_cover)
    monkeypatch.setattr(
        downloader.artwork, "make_audio_thumbnail", lambda ffmpeg, image, dest: thumbnails.append((image, dest))
    )
    monkeypatch.setattr(downloader, "_tag_sync", lambda path, track, cover: embedded.append(cover))

    path = asyncio.run(download_and_tag(_settings(tmp_path, None), "abc", TRACK))
    assert thumbnails == [(webp, path.parent / "vignette.jpg")]
    assert embedded == [None]


def test_youtube_url_keeps_the_whole_cascade(monkeypatch):
    seen = _recording_ytdlp(monkeypatch, BOT_WALL)
    with pytest.raises(DownloadError) as caught:
        _download_sync(
            "https://www.youtube.com/watch?v=abc", "out.%(ext)s", "ffmpeg", "best", "auto", Path("cookies.txt")
        )
    assert len(seen) == len(downloader._ATTEMPTS)
    assert caught.value.bot_wall
