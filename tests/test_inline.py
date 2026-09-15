import asyncio
import tempfile
from pathlib import Path

from app.bot.handlers.inline import _description
from app.db.database import Database
from app.db.repository import Repository
from app.providers.base import TrackInfo


def run(coro):
    return asyncio.run(coro)


def _track(source="deezer", source_id="1", album="Random Access Memories", duration=337):
    return TrackInfo(
        source=source,
        source_id=source_id,
        title="Instant Crush",
        artist="Daft Punk",
        album=album,
        year="2013",
        duration_seconds=duration,
        cover_url=None,
    )


def test_description_lists_artist_album_and_duration():
    assert _description(_track()) == "Daft Punk • Random Access Memories • 5:37"


def test_description_without_album():
    assert _description(_track(album=None)) == "Daft Punk • 5:37"


def _with_repo(scenario):
    async def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.db")
            await db.connect()
            try:
                await scenario(Repository(db))
            finally:
                await db.close()

    return run(wrapper())


def test_cache_lookup_returns_only_matching_entries():
    """Le panneau de suggestions interroge le cache en lot à chaque frappe :
    il doit renvoyer les morceaux déjà prêts, et rien d'autre."""

    async def scenario(repo: Repository):
        await repo.cache_set("deezer", "1", "auto", "best", "FILE_1", "u1")
        await repo.cache_set("deezer", "2", "auto", "best", "FILE_2", "u2")

        found = await repo.cache_get_many(
            [("deezer", "1"), ("deezer", "2"), ("deezer", "3")], "auto", "best"
        )
        assert found == {("deezer", "1"): "FILE_1", ("deezer", "2"): "FILE_2"}

    _with_repo(scenario)


def test_cache_lookup_does_not_mix_up_sources():
    """Le filtre SQL ne porte que sur source_id : un même identifiant chez deux
    sources différentes ne doit pas se retrouver attribué à la mauvaise."""

    async def scenario(repo: Repository):
        await repo.cache_set("youtube", "1", "auto", "best", "YT_FILE", "u")
        found = await repo.cache_get_many([("deezer", "1")], "auto", "best")
        assert found == {}

    _with_repo(scenario)


def test_cache_lookup_respects_format_and_quality():
    async def scenario(repo: Repository):
        await repo.cache_set("deezer", "1", "mp3", "standard", "FILE_MP3", "u")
        assert await repo.cache_get_many([("deezer", "1")], "auto", "best") == {}
        assert await repo.cache_get_many([("deezer", "1")], "mp3", "standard") == {
            ("deezer", "1"): "FILE_MP3"
        }

    _with_repo(scenario)


def test_cache_lookup_with_no_keys_does_not_query():
    async def scenario(repo: Repository):
        assert await repo.cache_get_many([], "auto", "best") == {}

    _with_repo(scenario)
