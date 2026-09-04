import asyncio

from app.providers.link_detect import resolve_link


def run(coro):
    return asyncio.run(coro)


def test_deezer_track():
    d = run(resolve_link("écoute ça https://www.deezer.com/fr/track/1234567890 trop bien"))
    assert d is not None
    assert (d.source, d.kind, d.ref) == ("deezer", "track", "1234567890")


def test_deezer_album_no_locale():
    d = run(resolve_link("https://www.deezer.com/album/987654"))
    assert (d.source, d.kind, d.ref) == ("deezer", "album", "987654")


def test_spotify_track_with_query():
    d = run(resolve_link("https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp?si=abc123"))
    assert (d.source, d.kind, d.ref) == ("spotify", "track", "3n3Ppam7vgaVa1iaRUc9Lp")


def test_spotify_intl_locale():
    d = run(resolve_link("https://open.spotify.com/intl-fr/album/4aawyAB9vmqN3uQ7FjRGTy"))
    assert (d.source, d.kind, d.ref) == ("spotify", "album", "4aawyAB9vmqN3uQ7FjRGTy")


def test_apple_music_track_with_i_param():
    url = "https://music.apple.com/fr/album/jefe/1440833926?i=1440833929"
    d = run(resolve_link(url))
    assert (d.source, d.kind, d.ref) == ("apple", "track", "1440833929")


def test_apple_music_album_without_i():
    url = "https://music.apple.com/fr/album/jefe/1440833926"
    d = run(resolve_link(url))
    assert (d.source, d.kind, d.ref) == ("apple", "album", "1440833926")


def test_apple_music_artist():
    url = "https://music.apple.com/fr/artist/saif/123456"
    d = run(resolve_link(url))
    assert (d.source, d.kind, d.ref) == ("apple", "artist", "123456")


def test_youtube_watch():
    d = run(resolve_link("regarde https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=xyz"))
    assert (d.source, d.kind, d.ref) == ("youtube", "track", "dQw4w9WgXcQ")


def test_youtube_music_watch():
    d = run(resolve_link("https://music.youtube.com/watch?v=dQw4w9WgXcQ"))
    assert (d.source, d.kind, d.ref) == ("youtube", "track", "dQw4w9WgXcQ")


def test_youtube_short_link():
    d = run(resolve_link("https://youtu.be/dQw4w9WgXcQ?si=abc"))
    assert (d.source, d.kind, d.ref) == ("youtube", "track", "dQw4w9WgXcQ")


def test_youtube_playlist():
    d = run(resolve_link("https://www.youtube.com/playlist?list=PLabcdef123"))
    assert (d.source, d.kind, d.ref) == ("youtube", "playlist", "PLabcdef123")


def test_no_link_in_plain_text():
    d = run(resolve_link("Saif Jefe"))
    assert d is None


def test_unrelated_url():
    d = run(resolve_link("https://example.com/foo"))
    assert d is None
