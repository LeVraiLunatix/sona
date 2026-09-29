"""Radio DJ : tempos enchaînés, artistes alternés, suite sans doublon."""

from __future__ import annotations

import random

from app.providers.base import ArtistInfo, TrackInfo
from app.services import djradio
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def track(i, artist, bpm):
    return TrackInfo("deezer", str(i), f"T{i}", artist, None, None, 180, None, artist_source_id=artist, bpm=bpm)


def test_tempo_distance_handles_half_and_double():
    assert djradio.tempo_distance(140, 70) == 0
    assert djradio.tempo_distance(120, 124) < 0.04
    assert djradio.tempo_distance(None, 120) == 0.12


def test_chain_follows_tempo_and_alternates_artists():
    candidates = [track(1, "a", 100), track(2, "b", 128), track(3, "c", 126), track(4, "d", 90), track(5, "b", 125)]
    out = djradio.chain(127, "seed", candidates, 4, random.Random(1))
    # Les tempos calables d'abord ; un artiste des deux derniers titres ne
    # revient pas, même avec le bon tempo.
    assert all(abs(t.bpm - 127) <= 2 for t in out[:2])
    assert out[2].bpm in (90, 100)
    for previous, current in zip(out, out[1:]):
        assert previous.artist != current.artist


class DjDeezer:
    def __init__(self):
        self.tracks = {str(i): track(i, f"art{i % 5}", 120 + i) for i in range(1, 30)}
        self.tracks["0"] = track(0, "seed", 121)

    async def get_track(self, track_id):
        return self.tracks[track_id]

    async def search_tracks(self, query, limit=25):
        return [self.tracks["0"]], 1

    async def get_artist_radio(self, artist_id, limit=25):
        return [TrackInfo(t.source, t.source_id, t.title, t.artist, None, None, 180, None) for t in list(self.tracks.values())[1:20]]

    async def get_related_artists(self, artist_id, limit=20):
        return [ArtistInfo("deezer", f"art{i}", f"art{i}", None) for i in range(5)]

    async def get_artist_top_tracks(self, artist_id, limit=25):
        return [t for t in self.tracks.values() if t.artist == artist_id][:limit]


def test_dj_radio_endpoint(client):
    client.deps.deezer = DjDeezer()
    me = login(client, "alice")
    got = client.get("/djradio/youtube/xyz", headers=me, params={"title": "T0", "artist": "seed", "exclude": "1,2"})
    assert got.status_code == 200
    ids = [t["source_id"] for t in got.json()]
    assert len(ids) == djradio.BATCH and len(set(ids)) == len(ids)
    assert not {"0", "1", "2"} & set(ids)
    assert all(t["bpm"] for t in got.json())  # tempo complété par la fiche
