"""Covers de radios : choix de l'artiste, détourage, route publique bornée."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from app.providers.base import TrackInfo
from app.services import radio_covers
from tests.test_api_browse import client  # noqa: F401  (client : fixture)


def track(artist_id: str) -> TrackInfo:
    return TrackInfo(source="deezer", source_id=artist_id, title="t", artist="a", album=None,
                     year=None, duration_seconds=1, cover_url=None, artist_source_id=artist_id)


def test_candidates_prefer_the_most_present_artist_not_already_shown():
    tracks = [track("1"), track("2"), track("2"), track("3"), track("3"), track("3")]
    assert radio_covers.candidates(tracks, set()) == ["3", "2", "1"]
    assert radio_covers.candidates(tracks, {"3"}) == ["2", "1"]
    assert radio_covers.candidates(tracks, {"1", "2", "3"}) == ["3", "2", "1"]


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(out, "PNG")
    return out.getvalue()


def test_cut_out_crops_to_the_person_and_rejects_a_full_picture():
    def half(image):
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).ellipse((20, 10, 69, 129), fill=255)  # tête ronde, corps coupé en bas
        return mask

    portrait = Image.open(io.BytesIO(radio_covers.cut_out(png(), half)))
    assert portrait.size == (50, 90)
    assert radio_covers.cut_out(png(), lambda i: Image.new("L", i.size, 255)) is None
    assert radio_covers.cut_out(png(), lambda i: Image.new("L", i.size, 0)) is None

    def rectangle(image):
        mask = Image.new("L", image.size, 0)
        mask.paste(255, (20, 10, 70, 100))
        return mask

    assert radio_covers.cut_out(png(), rectangle) is None


def test_cover_route_serves_only_curated_radios(client, tmp_path, monkeypatch):
    monkeypatch.setattr(radio_covers, "cover_dir", lambda settings: tmp_path)
    monkeypatch.setattr(radio_covers, "MODEL_NAME", "absent.onnx")
    assert client.get("/radios/1/cover").status_code == 404
    assert client.get("/radios/39021/cover").status_code == 404
    (tmp_path / "39021.webp").write_bytes(b"portrait")
    got = client.get("/radios/39021/cover")
    assert got.status_code == 200 and got.content == b"portrait"
