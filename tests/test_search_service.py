import asyncio
from types import SimpleNamespace

import pytest

from app.providers.apple import AppleMusicError
from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError
from app.services import query_cache, search


def run(coro):
    return asyncio.run(coro)


def make_track(source, index):
    return TrackInfo(
        source=source,
        source_id=str(index),
        title=f"Titre {index}",
        artist="Artiste",
        album=None,
        year=None,
        duration_seconds=200,
        cover_url=None,
    )


class FakeDeezer:
    def __init__(self, error=None, results=None):
        self.error = error
        self.results = results if results is not None else [make_track("deezer", i) for i in range(10)]
        self.calls = 0

    async def search_tracks(self, query, index=0, limit=25):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results[index : index + limit], len(self.results)

    async def search_tracks_by_artist(self, artist_name, query, index=0, limit=25):
        return await self.search_tracks(f"{artist_name} {query}", index=index, limit=limit)


class FakeApple:
    def __init__(self, error=None, results=None):
        self.error = error
        self.results = results if results is not None else [make_track("apple", i) for i in range(7)]
        self.calls = 0

    async def search_tracks(self, query, limit=25):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results[:limit]


def make_deps(deezer, apple):
    return SimpleNamespace(deezer=deezer, apple=apple)


def test_deezer_is_used_first():
    deezer, apple = FakeDeezer(), FakeApple()
    cached = query_cache.CachedQuery(text="daft punk")
    tracks, total = run(search.search_tracks(make_deps(deezer, apple), cached, index=0, limit=5))
    assert [t.source for t in tracks] == ["deezer"] * 5
    assert total == 10
    assert cached.provider == "deezer"
    assert apple.calls == 0


def test_apple_takes_over_when_deezer_is_down():
    deezer = FakeDeezer(error=DeezerError("503"))
    apple = FakeApple()
    cached = query_cache.CachedQuery(text="daft punk")
    tracks, total = run(search.search_tracks(make_deps(deezer, apple), cached, index=0, limit=5))
    assert [t.source for t in tracks] == ["apple"] * 5
    assert total == 7
    assert cached.provider == "apple"


def test_apple_takes_over_when_deezer_knows_nothing():
    deezer = FakeDeezer(results=[])
    apple = FakeApple()
    cached = query_cache.CachedQuery(text="titre obscur")
    tracks, _ = run(search.search_tracks(make_deps(deezer, apple), cached, index=0, limit=5))
    assert [t.source for t in tracks] == ["apple"] * 5


def test_pagination_stays_on_the_chosen_provider():
    """Une fois la source retenue, les pages suivantes ne repartent pas sur
    Deezer : l'utilisateur garderait sinon une liste incohérente."""
    deezer = FakeDeezer(error=DeezerError("503"))
    apple = FakeApple()
    deps = make_deps(deezer, apple)
    cached = query_cache.CachedQuery(text="daft punk")
    run(search.search_tracks(deps, cached, index=0, limit=5))
    calls_after_first = deezer.calls

    page2, _ = run(search.search_tracks(deps, cached, index=5, limit=5))
    assert [t.source_id for t in page2] == ["5", "6"]
    assert deezer.calls == calls_after_first


def test_empty_result_is_not_an_error(monkeypatch):
    async def no_youtube(query, limit=20):
        return []

    monkeypatch.setattr(search, "search_tracks_youtube", no_youtube)
    monkeypatch.setattr(search, "search_tracks_youtube_raw", no_youtube)
    deezer, apple = FakeDeezer(results=[]), FakeApple(results=[])
    cached = query_cache.CachedQuery(text="azerty qwerty")
    tracks, total = run(search.search_tracks(make_deps(deezer, apple), cached))
    assert tracks == [] and total == 0


def test_all_providers_down_raises_search_error(monkeypatch):
    async def broken_youtube(query, limit=20):
        raise RuntimeError("réseau coupé")

    monkeypatch.setattr(search, "search_tracks_youtube", broken_youtube)
    monkeypatch.setattr(search, "search_tracks_youtube_raw", broken_youtube)
    deezer = FakeDeezer(error=DeezerError("503"))
    apple = FakeApple(error=AppleMusicError("503"))
    cached = query_cache.CachedQuery(text="daft punk")
    with pytest.raises(search.SearchError):
        run(search.search_tracks(make_deps(deezer, apple), cached))
