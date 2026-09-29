"""Choix de la version audio (audio officiel plutôt que clip) et
« Mauvaise version ? » : source écartée, cache supprimé, plus jamais reprise."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.base import TrackInfo
from app.services import resolver
from app.services.resolver import AUDIO_TRACK_TYPE, MUSIC_VIDEO_TYPE, Candidate, rank_candidates

AUTH = {"Authorization": "Bearer test-token"}
TRACK = TrackInfo("deezer", "77", "7/7", "PLK", "2069", None, 156, None)


def cand(video_id, title, *, video_type=None, is_song=False, duration=156, artist="PLK"):
    return Candidate(
        video_id=video_id, title=title, artist=artist, album=None, duration_seconds=duration,
        cover_url=None, is_song=is_song, video_type=video_type,
    )


def test_audio_track_beats_the_clip():
    clip = cand("clip", "PLK - 7/7 (Clip officiel)", video_type=MUSIC_VIDEO_TYPE, duration=157)
    audio = cand("audio", "7/7", video_type=AUDIO_TRACK_TYPE, is_song=True, duration=160)
    assert [c.video_id for c in rank_candidates(TRACK, [clip, audio])] == ["audio", "clip"]


def test_clip_words_are_penalised_without_video_type():
    clip = cand("clip", "PLK - 7/7 (Clip Officiel)")
    plain = cand("plain", "PLK - 7/7")
    assert [c.video_id for c in rank_candidates(TRACK, [clip, plain])] == ["plain", "clip"]


def test_excluded_sources_are_never_offered(monkeypatch):
    found = [
        cand("audio", "7/7", video_type=AUDIO_TRACK_TYPE, is_song=True),
        cand("other", "7/7", is_song=True, duration=158),
    ]
    monkeypatch.setattr(resolver, "_search_ytmusic_sync", lambda queries: list(found))
    monkeypatch.setattr(resolver, "_search_soundcloud_sync", lambda query: [])
    monkeypatch.setattr(resolver, "_search_ytdlp_sync", lambda query, cookies: [])

    async def collect():
        return [c.video_id async for c in resolver.iter_audio_sources(TRACK, None, {"audio"})]

    assert asyncio.run(collect()) == ["other"]


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


def test_wrong_version_rejects_source_and_clears_cache(client, tmp_path):
    repo = client.deps.repo
    cached = tmp_path / "deezer_77.m4a"
    cached.write_bytes(b"clip")

    async def seed():
        await repo.stream_cache_set("deezer", "77", "auto", "best", str(cached), "audio/mp4")
        await repo.stream_source_set("deezer", "77", "clip")

    client.portal.call(seed)
    got = client.post("/stream/deezer/77/wrong-version", headers=AUTH)
    assert got.status_code == 200 and got.json() == {"rejected": "clip"}
    assert not cached.exists()

    async def check():
        return (
            await repo.rejected_sources("deezer", "77"),
            await repo.stream_cache_get("deezer", "77", "auto", "best"),
            await repo.stream_source_get("deezer", "77"),
        )

    assert client.portal.call(check) == ({"clip"}, None, None)


def test_wrong_version_without_known_source_still_clears_cache(client, tmp_path):
    cached = tmp_path / "old.m4a"
    cached.write_bytes(b"x")
    client.portal.call(client.deps.repo.stream_cache_set, "deezer", "5", "auto", "best", str(cached), "audio/mp4")
    got = client.post("/stream/deezer/5/wrong-version", headers=AUTH)
    assert got.json() == {"rejected": None}
    assert not cached.exists()
