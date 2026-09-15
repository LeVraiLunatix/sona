import os
import time
from pathlib import Path

import pytest

from app.services.downloader import (
    DownloadError,
    _find_output,
    _format_selector_for,
    _sanitize_filename,
    cleanup_download,
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
