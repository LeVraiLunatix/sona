import asyncio
import random
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.providers.base import TrackInfo
from app.services import audio_match
from app.services.audio_match import SAME_RECORDING_MAX_ERROR, Verdict, alignment_error, verify_recording


def fingerprint(length, seed):
    rng = random.Random(seed)
    return [rng.getrandbits(32) for _ in range(length)]


def track(preview_url="https://cdn.example/preview.mp3"):
    return TrackInfo(
        source="deezer",
        source_id="1",
        title="Au DD",
        artist="PNL",
        album="Au DD",
        year="2019",
        duration_seconds=247,
        cover_url=None,
        preview_url=preview_url,
    )


def test_identical_recordings_have_no_error():
    fp = fingerprint(200, seed=1)
    assert alignment_error(fp, fp) == 0.0


def test_excerpt_is_found_wherever_it_sits_in_the_track():
    """L'extrait Deezer vient d'un endroit inconnu du morceau."""
    full = fingerprint(2000, seed=2)
    excerpt = full[1234:1474]
    assert alignment_error(excerpt, full) == 0.0
    # L'ordre des arguments n'a pas d'importance.
    assert alignment_error(full, excerpt) == 0.0


def test_reencoded_copy_is_still_the_same_recording():
    """Un repost réencodé change quelques bits de l'empreinte, pas davantage."""
    rng = random.Random(5)
    full = fingerprint(1000, seed=6)
    excerpt = [v ^ (1 << rng.randrange(32)) if rng.random() < 0.5 else v for v in full[300:540]]
    assert alignment_error(excerpt, full) < SAME_RECORDING_MAX_ERROR


def test_unrelated_recordings_are_far_above_the_threshold():
    assert alignment_error(fingerprint(240, seed=3), fingerprint(2000, seed=4)) > 2 * SAME_RECORDING_MAX_ERROR


def test_only_a_measured_mismatch_is_rejected():
    assert not Verdict(None, "pas d'extrait officiel").rejected
    assert not Verdict(0.06).rejected
    assert Verdict(0.31).rejected


def test_verification_is_skipped_without_official_excerpt():
    verdict = asyncio.run(verify_recording(track(preview_url=None), Path("absent.m4a"), "ffmpeg"))
    assert verdict.error is None
    assert not verdict.rejected


def test_verification_is_skipped_when_ffmpeg_lacks_chromaprint(monkeypatch):
    monkeypatch.setattr(audio_match, "chromaprint_available", lambda ffmpeg_path: False)
    verdict = asyncio.run(verify_recording(track(), Path("absent.m4a"), "ffmpeg"))
    assert verdict.error is None
    assert not verdict.rejected


def _fake_fingerprints(monkeypatch, excerpt, full):
    async def fetch(url):
        return b"extrait"

    monkeypatch.setattr(audio_match, "chromaprint_available", lambda ffmpeg_path: True)
    monkeypatch.setattr(audio_match, "_fetch_preview", fetch)
    monkeypatch.setattr(
        audio_match, "fingerprint", lambda ffmpeg_path, path: excerpt if path.name == "preview" else full
    )


def test_other_recording_under_the_same_title_is_rejected(monkeypatch):
    _fake_fingerprints(monkeypatch, excerpt=fingerprint(240, seed=7), full=fingerprint(2000, seed=8))
    verdict = asyncio.run(verify_recording(track(), Path("repost.m4a"), "ffmpeg"))
    assert verdict.rejected


def test_official_recording_is_accepted(monkeypatch):
    full = fingerprint(2000, seed=9)
    _fake_fingerprints(monkeypatch, excerpt=full[800:1040], full=full)
    verdict = asyncio.run(verify_recording(track(), Path("officiel.m4a"), "ffmpeg"))
    assert verdict.error == 0.0
    assert not verdict.rejected


def test_thirty_second_snippet_is_rejected_although_it_matches_the_excerpt(monkeypatch):
    """Titre SoundCloud réservé aux abonnés : le fichier n'est que l'extrait,
    donc identique à l'extrait officiel, mais ce n'est pas le morceau."""
    excerpt = fingerprint(240, seed=10)
    _fake_fingerprints(monkeypatch, excerpt=excerpt, full=excerpt)
    monkeypatch.setattr(audio_match, "_audio_length", lambda path: 30.0)
    verdict = asyncio.run(verify_recording(track(), Path("extrait.m4a"), "ffmpeg"))
    assert verdict.rejected
    assert "30 s" in verdict.reason


def test_slightly_different_length_is_still_compared(monkeypatch):
    full = fingerprint(2000, seed=11)
    _fake_fingerprints(monkeypatch, excerpt=full[100:340], full=full)
    monkeypatch.setattr(audio_match, "_audio_length", lambda path: 251.0)
    verdict = asyncio.run(verify_recording(track(), Path("officiel.m4a"), "ffmpeg"))
    assert verdict.error == 0.0


def test_ffmpeg_never_reads_the_standard_input(monkeypatch):
    """Sans `-nostdin`, ffmpeg consomme l'entrée standard : lancé depuis un
    script (`ssh … bash -s`), il en avale des morceaux."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[-1]).write_bytes((7).to_bytes(4, "little") * 50)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(audio_match.subprocess, "run", fake_run)
    assert audio_match.fingerprint("ffmpeg", Path("audio.m4a")) == [7] * 50
    args, kwargs = calls[0]
    assert "-nostdin" in args
    assert kwargs.get("stdin") is subprocess.DEVNULL
