import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.providers.deezer import _album_from_json, _artist_from_json, _track_from_json
from app.services import artwork
from app.services.artwork import AUDIO_THUMBNAIL_MAX_BYTES, is_embeddable, make_audio_thumbnail, resize_artwork_url

DEEZER_COVER = "https://cdn-images.dzcdn.net/images/cover/6e14fef7ed2c5684a36badd00b693036/{size}-000000-80-0-0.jpg"


def test_deezer_cover_can_be_requested_at_another_size():
    assert resize_artwork_url(DEEZER_COVER.format(size="1000x1000"), 250) == DEEZER_COVER.format(size="250x250")


def test_apple_and_youtube_music_artwork_are_resized():
    apple = "https://is1-ssl.mzstatic.com/image/thumb/Music/v4/ab/cd/100x100bb.jpg"
    assert resize_artwork_url(apple, 1000) == "https://is1-ssl.mzstatic.com/image/thumb/Music/v4/ab/cd/1000x1000bb.jpg"
    google = "https://yt3.googleusercontent.com/abc=w120-h120-l90-rj"
    assert resize_artwork_url(google, 1000) == "https://yt3.googleusercontent.com/abc=w1000-h1000-l90-rj"


def test_artwork_url_without_size_is_left_untouched():
    url = "https://i.ytimg.com/vi/abc/maxresdefault.jpg"
    assert resize_artwork_url(url, 1000) == url
    assert resize_artwork_url(None, 1000) is None


def test_deezer_uses_the_largest_images():
    """La pochette 250 px de Deezer était pixelisée une fois affichée en grand."""
    track = _track_from_json({
        "id": 1,
        "title": "Hasta la vista",
        "artist": {"id": 2, "name": "PNL"},
        "album": {
            "id": 3,
            "title": "Deux frères",
            "cover_medium": DEEZER_COVER.format(size="250x250"),
            "cover_xl": DEEZER_COVER.format(size="1000x1000"),
        },
    })
    assert track.cover_url == DEEZER_COVER.format(size="1000x1000")
    album = _album_from_json({"id": 3, "cover_medium": "petite", "cover_big": "moyenne", "cover_xl": "grande"})
    assert album.cover_url == "grande"
    artist = _artist_from_json({"id": 2, "picture_medium": "petite", "picture_xl": "grande"})
    assert artist.picture_url == "grande"


def test_only_jpeg_and_png_can_be_embedded():
    assert is_embeddable(b"\xff\xd8\xff\xe0reste")
    assert is_embeddable(b"\x89PNG\r\n\x1a\nreste")
    assert not is_embeddable(b"RIFF\x00\x00\x00\x00WEBPVP8 ")


def _fake_ffmpeg(monkeypatch, output=b"\xff\xd8\xff" + b"0" * 1000, error=None):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if error:
            raise error
        Path(args[-1]).write_bytes(output)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(artwork.subprocess, "run", run)
    return calls


def test_audio_thumbnail_is_a_square_crop_within_telegram_limits(monkeypatch, tmp_path):
    calls = _fake_ffmpeg(monkeypatch)
    dest = tmp_path / artwork.AUDIO_THUMBNAIL_NAME
    assert make_audio_thumbnail("ffmpeg", b"image", dest) == dest
    args, kwargs = calls[0]
    assert "crop=320:320" in args[args.index("-vf") + 1]
    # Sans `-nostdin`, ffmpeg lit l'entrée standard (voir audio_match).
    assert "-nostdin" in args
    assert kwargs["stdin"] is subprocess.DEVNULL
    # L'image source temporaire ne traîne pas.
    assert [p.name for p in tmp_path.iterdir()] == [artwork.AUDIO_THUMBNAIL_NAME]


def test_oversized_thumbnail_is_dropped(monkeypatch, tmp_path):
    _fake_ffmpeg(monkeypatch, output=b"0" * (AUDIO_THUMBNAIL_MAX_BYTES + 1))
    assert make_audio_thumbnail("ffmpeg", b"image", tmp_path / artwork.AUDIO_THUMBNAIL_NAME) is None
    assert not list(tmp_path.iterdir())


def test_ffmpeg_failure_means_no_thumbnail(monkeypatch, tmp_path):
    _fake_ffmpeg(monkeypatch, error=subprocess.CalledProcessError(1, ["ffmpeg"]))
    assert make_audio_thumbnail("ffmpeg", b"image", tmp_path / artwork.AUDIO_THUMBNAIL_NAME) is None
    assert not list(tmp_path.iterdir())
