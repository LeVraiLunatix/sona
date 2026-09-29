"""Analyse audio pour l'AutoMix, à partir d'une sortie `ebur128` de ffmpeg
reconstituée (ffmpeg n'est pas nécessaire aux tests)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.audio_analysis import parse_ebur128


def fake_stderr(profile: list[tuple[float, float]], integrated: float) -> str:
    """`profile` : (jusqu'à t secondes, sonie) par tranche."""
    lines, t, i = [], 0.0, 0
    while i < len(profile):
        until, level = profile[i]
        while t < until:
            t = round(t + 0.1, 1)
            lines.append(
                f"[Parsed_ebur128_0 @ 0x55] t: {t}   TARGET:-23 LUFS    M: {level:.1f} S: {level:.1f}     "
                f"I: {integrated:.1f} LUFS       LRA:   5.0 LU"
            )
        i += 1
    lines += ["[Parsed_ebur128_0 @ 0x55] Summary:", "", "  Integrated loudness:", f"    I:         {integrated} LUFS",
              "    Threshold: -19.0 LUFS"]
    return "\n".join(lines)


def test_parse_finds_start_outro_and_end():
    stderr = fake_stderr(
        [(1.5, -120.0), (150.0, -8.0), (170.0, -20.0), (175.0, -70.0)],  # blanc, titre, outro calme, silence
        integrated=-9.0,
    )
    analysis = parse_ebur128(stderr)
    assert analysis.loudness == -9.0
    assert 1.1 <= analysis.start <= 1.5
    assert 149.0 <= analysis.mix_out <= 150.5   # le titre retombe à 150 s
    assert 169.9 <= analysis.end <= 170.5       # silence final ignoré
    assert analysis.duration == 175.0


def test_parse_abrupt_ending_keeps_a_short_mix():
    analysis = parse_ebur128(fake_stderr([(180.0, -8.0)], integrated=-8.0))
    assert analysis.end - analysis.mix_out == pytest.approx(3.0, abs=0.4)


def test_parse_rejects_garbage():
    assert parse_ebur128("rien") is None


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.deps = main_module.app.state.deps
        yield test_client


def test_analysis_endpoint(client):
    auth = {"Authorization": "Bearer test-token"}
    assert client.get("/analysis/deezer/1", headers=auth).status_code == 404
    client.portal.call(client.deps.repo.analysis_set, "deezer", "1", -9.0, 1.2, 150.0, 170.0, 175.0)
    assert client.get("/analysis/deezer/1", headers=auth).json() == {
        "loudness": -9.0, "start": 1.2, "mix_out": 150.0, "end": 170.0, "duration": 175.0,
    }
