from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

URL_RE = re.compile(r"https?://\S+")

_DEEZER_RE = re.compile(
    r"deezer\.com/(?:[a-z]{2}/)?(track|album|artist|playlist)/(\d+)", re.IGNORECASE
)
_DEEZER_SHORT_RE = re.compile(
    r"(?:deezer\.page\.link|link\.deezer\.com)/\S+", re.IGNORECASE
)
_SPOTIFY_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}/)?(track|album|artist|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_APPLE_RE = re.compile(
    r"music\.apple\.com/([a-z]{2})/(album|artist|playlist)/[^/?]+/([A-Za-z0-9.]+)",
    re.IGNORECASE,
)
_YOUTUBE_WATCH_RE = re.compile(
    r"(?:music\.)?youtube\.com/watch\?[^ ]*\bv=([A-Za-z0-9_-]{6,})", re.IGNORECASE
)
_YOUTUBE_SHORT_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})", re.IGNORECASE)
_YOUTUBE_PLAYLIST_RE = re.compile(
    r"(?:music\.)?youtube\.com/playlist\?[^ ]*\blist=([A-Za-z0-9_-]+)", re.IGNORECASE
)


@dataclass(slots=True)
class DetectedLink:
    source: str  # "deezer" | "spotify" | "apple" | "youtube"
    kind: str  # "track" | "album" | "artist" | "playlist"
    ref: str  # id, or for apple: "<store>:<id>", for youtube video id


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    return match.group(0) if match else None


def _parse(url: str) -> DetectedLink | None:
    m = _DEEZER_RE.search(url)
    if m:
        kind, ref = m.group(1).lower(), m.group(2)
        return DetectedLink("deezer", kind, ref)

    m = _SPOTIFY_RE.search(url)
    if m:
        kind, ref = m.group(1).lower(), m.group(2)
        return DetectedLink("spotify", kind, ref)

    m = _APPLE_RE.search(url)
    if m:
        kind = m.group(2).lower()
        ref = m.group(3)
        # Un lien de morceau Apple Music est un lien d'album avec ?i=<track_id>
        i_match = re.search(r"[?&]i=(\d+)", url)
        if i_match:
            return DetectedLink("apple", "track", i_match.group(1))
        return DetectedLink("apple", kind, ref)

    m = _YOUTUBE_PLAYLIST_RE.search(url)
    if m:
        return DetectedLink("youtube", "playlist", m.group(1))

    m = _YOUTUBE_WATCH_RE.search(url)
    if m:
        return DetectedLink("youtube", "track", m.group(1))

    m = _YOUTUBE_SHORT_RE.search(url)
    if m:
        return DetectedLink("youtube", "track", m.group(1))

    return None


async def resolve_link(text: str) -> DetectedLink | None:
    """Détecte un lien Deezer/Spotify/Apple Music/YouTube dans un texte libre.

    Résout aussi les liens courts Deezer (deezer.page.link / link.deezer.com)
    en suivant la redirection avant analyse.
    """
    url = extract_first_url(text)
    if not url:
        return None

    detected = _parse(url)
    if detected:
        return detected

    if _DEEZER_SHORT_RE.search(url):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                resp = await client.head(url)
                final_url = str(resp.url)
        except httpx.HTTPError:
            return None
        return _parse(final_url)

    return None
