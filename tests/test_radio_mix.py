"""Radios construites sur les playlists : fusion des sources et tirage."""

from __future__ import annotations

import random

from app.api.routers import browse
from app.providers.base import TrackInfo
from app.services import radio_mix


def track(title: str, artist: str) -> TrackInfo:
    return TrackInfo(source="deezer", source_id=f"{title}-{artist}", title=title, artist=artist,
                     album=None, year=None, duration_seconds=1, cover_url=None, artist_source_id=artist)


def test_every_curated_radio_has_a_theme():
    assert {rid for _, radios in browse.CURATED_RADIOS for rid, _ in radios} == set(radio_mix.THEMES)


def test_same_song_across_services():
    assert radio_mix.key("Été (feat. X) - Radio Edit", "Naïma, Bob") == radio_mix.key("ete", "Naima")


def test_merge_puts_the_most_agreed_songs_first():
    a, b, c = track("A", "1"), track("B", "2"), track("C", "3")
    pool = radio_mix.merge([(1.0, [a, b, b]), (1.0, [b]), (0.7, [c])], chart={radio_mix.key("C", "3")})
    assert [t.title for _, t in pool] == ["C", "B", "A"]
    assert [score for score, _ in pool] == [2.2, 2.0, 1.0]


def test_draw_limits_and_spaces_artists():
    pool = [(1.0, track(f"t{i}", "same")) for i in range(10)] + [(1.0, track(f"o{i}", f"a{i}")) for i in range(10)]
    for seed in range(20):
        got = radio_mix.draw(pool, 8, random.Random(seed))
        assert len(got) == 8
        assert sum(t.artist == "same" for t in got) <= 2
        assert all(x.artist != y.artist for x, y in zip(got, got[1:]))


def test_editorial_playlists_only():
    editor = {"user": {"name": "Yannick - Deezer Jazz & Blues Editor"}, "nb_tracks": 80}
    assert radio_mix.editorial(editor)
    assert not radio_mix.editorial({**editor, "user": {"name": "bob"}})
    assert not radio_mix.editorial({**editor, "nb_tracks": 5})
