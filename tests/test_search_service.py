import asyncio
from types import SimpleNamespace

import pytest

from app.providers.apple import AppleMusicError
from app.providers.base import ArtistInfo, TrackInfo
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

    async def search_artists(self, query, limit=10):
        if self.error:
            raise self.error
        return list(self.artists)

    async def get_artist_top_tracks(self, artist_id, limit=25):
        return [make_track("deezer", f"top-{artist_id}-{i}") for i in range(3)]

    artists: list = []


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


def test_misspelled_artist_name_returns_that_artist_top_tracks():
    """« eiak » : la recherche de morceaux Deezer ne trouve rien, sa
    recherche d'artistes (tolérante) trouve Ziak — ses titres populaires
    passent avant iTunes/YouTube."""
    deezer, apple = FakeDeezer(results=[]), FakeApple()
    deezer.artists = [ArtistInfo(source="deezer", source_id="7668530", name="Ziak", picture_url=None, fans=626134)]
    cached = query_cache.CachedQuery(text="eiak")
    tracks, total = run(search.search_tracks(make_deps(deezer, apple), cached, index=0, limit=5))
    assert [t.source_id for t in tracks] == ["top-7668530-0", "top-7668530-1", "top-7668530-2"]
    assert cached.provider == "deezer_artist"
    assert apple.calls == 0


def test_unrelated_artist_is_not_used_for_an_unknown_title():
    deezer, apple = FakeDeezer(results=[]), FakeApple()
    deezer.artists = [ArtistInfo(source="deezer", source_id="1", name="Sia", picture_url=None)]
    cached = query_cache.CachedQuery(text="titre obscur")
    tracks, _ = run(search.search_tracks(make_deps(deezer, apple), cached, index=0, limit=5))
    assert [t.source for t in tracks] == ["apple"] * 5
