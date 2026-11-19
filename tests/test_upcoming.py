import asyncio
from datetime import datetime, timezone

from app.api.schemas import Album
from app.providers import deezer
from app.providers.base import AlbumInfo, TrackInfo
from app.services import apple_motion, upcoming

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def track(title, date=None, source="deezer", sid="1"):
    return TrackInfo(source, sid, title, "Artiste", "Album", None, 180, None, release_date=date)


def album(date, tracks=(), cover="https://img/c.jpg", title="GTA VI"):
    return AlbumInfo("deezer", "9", title, "Artiste", "5", None, cover, len(tracks), None,
                     tracks=list(tracks), release_date=date)


def test_release_moment_is_midnight_in_paris():
    moment = upcoming.release_moment("2026-12-05")
    assert moment.isoformat() == "2026-12-05T00:00:00+01:00"
    assert upcoming.release_moment("2026-07-03").isoformat() == "2026-07-03T00:00:00+02:00"
    assert upcoming.release_moment("2026-12-05T08:00:00Z") == moment  # Apple : date et heure


def test_release_moment_ignores_missing_or_nonsense_dates():
    for value in (None, "", "2026", "0000-00-00", "pas une date"):
        assert upcoming.release_moment(value) is None
    assert not upcoming.is_upcoming("0000-00-00", NOW)


def test_is_upcoming_switches_at_paris_midnight():
    assert upcoming.is_upcoming("2026-11-20", NOW)
    assert not upcoming.is_upcoming("2026-11-19", NOW)  # sorti aujourd'hui à 00:00
    assert not upcoming.is_upcoming("2025-01-01", NOW)
    # 22 h 59 UTC le 19 : il est 23 h 59 à Paris, la sortie du 20 n'a pas eu lieu.
    assert upcoming.is_upcoming("2026-11-20", datetime(2026, 11, 19, 22, 59, tzinfo=timezone.utc))
    assert not upcoming.is_upcoming("2026-11-20", datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc))


def test_track_released_uses_its_own_date_then_the_albums():
    assert not upcoming.track_released(track("a"), "2026-12-05", NOW)
    assert upcoming.track_released(track("a", "2026-10-01"), "2026-12-05", NOW)  # single sorti avant
    assert upcoming.track_released(track("a"), None, NOW)  # aucune date : on le suppose sorti


def test_album_schema_flags_upcoming_album_and_greys_unreleased_tracks(monkeypatch):
    info = album("2999-12-05", [track("Single", "2026-01-01", sid="1"), track("Inédit", "2999-12-05", sid="2")])
    out = Album.from_info(info)
    assert out.upcoming is True
    assert out.release_at == "2999-12-05T00:00:00+01:00"
    assert [t.released for t in out.tracks] == [True, False]


def test_album_schema_for_released_album_has_no_countdown():
    out = Album.from_info(album("2020-05-01", [track("a")]))
    assert out.upcoming is False and out.release_at is None
    assert out.tracks[0].released is True


def test_deezer_blank_cover_is_not_a_cover():
    blank = {"cover_xl": "https://cdn-images.dzcdn.net/images/cover//1000x1000-000000-80-0-0.jpg"}
    assert deezer._largest_image(blank, "cover") is None
    ok = {"cover_xl": "https://cdn-images.dzcdn.net/images/cover/abc123/1000x1000-000000-80-0-0.jpg"}
    assert deezer._largest_image(ok, "cover") == ok["cover_xl"]


def test_track_release_date_falls_back_to_the_album():
    nested = {"id": 1, "title": "x", "artist": {"id": 2, "name": "A"},
              "album": {"id": 3, "title": "Y", "release_date": "2999-01-01"}}
    assert deezer._track_from_json(nested).release_date == "2999-01-01"
    own = {**nested, "release_date": "2026-01-01"}
    assert deezer._track_from_json(own).release_date == "2026-01-01"


def test_apple_artwork_url_and_album_match():
    template = {"url": "https://is1-ssl.mzstatic.com/image/thumb/x/{w}x{h}bb.{f}"}
    assert apple_motion.artwork_url(template) == "https://is1-ssl.mzstatic.com/image/thumb/x/1000x1000bb.jpg"
    assert apple_motion.artwork_url({"url": "http://x"}) is None
    results = [
        {"id": "1", "attributes": {"name": "GTA VI (Deluxe)", "artistName": "Artiste"}},
        {"id": "2", "attributes": {"name": "Autre", "artistName": "Artiste"}},
    ]
    assert apple_motion.find_album(results, "GTA VI", "Artiste")["id"] == "1"
    assert apple_motion.find_album(results, "GTA VI", "Quelqu'un d'autre") is None


def test_enrich_fills_missing_cover_and_tracklist_from_apple(monkeypatch):
    calls = []

    async def preview(title, artist, with_tracks=False):
        calls.append(with_tracks)
        return {"cover_url": "https://apple/cover.jpg", "release_date": "2999-12-05", "tracks": [
            {"id": "11", "title": "Intro", "artist": "Artiste", "duration": 90, "track": 1, "disc": 1,
             "release_date": "2999-12-05", "isrc": "X1"},
            {"id": "12", "title": "Single", "artist": "Artiste", "duration": 200, "track": 2, "disc": 1,
             "release_date": "2026-01-01", "isrc": "X2"},
        ]}

    monkeypatch.setattr(apple_motion, "album_preview", preview)
    info = album("2999-12-05", cover=None)
    asyncio.run(upcoming.enrich_albums([info]))
    assert calls == [True]
    assert info.cover_url == "https://apple/cover.jpg"
    assert [t.title for t in info.tracks] == ["Intro", "Single"]
    assert [t.cover_url for t in info.tracks] == ["https://apple/cover.jpg"] * 2
    out = Album.from_info(info)
    assert [t.released for t in out.tracks] == [False, True]


def test_enrich_does_nothing_for_a_complete_album(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("Apple ne doit pas être interrogé")

    monkeypatch.setattr(apple_motion, "album_preview", boom)
    asyncio.run(upcoming.enrich_albums([album("2020-01-01", [track("a")])]))


def test_enrich_survives_apple_being_down(monkeypatch):
    async def down(*args, **kwargs):
        raise RuntimeError("panne")

    monkeypatch.setattr(apple_motion, "album_preview", down)
    info = album("2999-12-05", cover=None)
    asyncio.run(upcoming.enrich_albums([info]))
    assert info.cover_url is None


def test_split_upcoming_orders_soonest_first():
    far, near, past = album("2999-12-05", title="Loin"), album("2998-01-01", title="Proche"), album("2020-01-01", title="Passé")
    ahead, released = upcoming.split_upcoming([far, past, near])
    assert [a.title for a in ahead] == ["Proche", "Loin"]
    assert [a.title for a in released] == ["Passé"]


def test_upcoming_releases_of_favourite_artists_soonest_first(monkeypatch):
    from app.services import releases

    async def favourites(deps, user_id, count=15):
        return [("A", "1"), ("B", "2")]

    class FakeDeezer:
        async def get_artist_albums(self, artist_id, name):
            if artist_id == "1":
                return [album("2999-12-05", title="Loin"), album("2020-01-01", title="Passé")], []
            return [], [album("2998-01-01", title="Proche")]

    async def preview(title, artist, with_tracks=False):
        return {"cover_url": "https://apple/c.jpg", "release_date": None, "tracks": []}

    class Deps:
        deezer = FakeDeezer()

    monkeypatch.setattr(releases, "favourite_artists", favourites)
    monkeypatch.setattr(apple_motion, "album_preview", preview)
    # `album()` donne le même identifiant aux trois : on les distingue.
    original = FakeDeezer.get_artist_albums

    async def distinct(self, artist_id, name):
        albums, singles = await original(self, artist_id, name)
        for index, a in enumerate(albums + singles):
            a.source_id = f"{artist_id}-{index}"
        return albums, singles

    monkeypatch.setattr(FakeDeezer, "get_artist_albums", distinct)
    found = asyncio.run(releases.upcoming_releases(Deps(), 1))
    assert [a.title for a in found] == ["Proche", "Loin"]
    assert all(a.cover_url == "https://apple/c.jpg" or a.cover_url for a in found)
