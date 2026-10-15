"""Versions d'un même album (standard, deluxe, expanded, remasterisé…).

Deezer liste chaque édition comme un album à part : la page d'un artiste
montrait donc l'album deux fois. Comme sur Apple Music, on garde la version
la plus récente en avant et les autres vont dans « Autres versions »."""

from __future__ import annotations

import re
import unicodedata

from app.providers.base import AlbumInfo

# Mots qui signalent une édition plutôt qu'un autre album.
_EDITION = (
    r"deluxe|luxe|edition|version|expanded|extended|bonus|remaster\w*|re-?issue|collector|anniversary|"
    r"anniversaire|special|complete|platinum|gold|explicit|clean|standard|tour|digital|streaming|"
    r"original|redux|\d+(?:th|st|nd|rd|e|eme)?\s*anniversary"
)
_EDITION_RE = re.compile(
    rf"\s*[\(\[][^)\]]*\b(?:{_EDITION})\b[^)\]]*[\)\]]|\s+[-–:]\s+[^-–:]*\b(?:{_EDITION})\b.*$",
    re.IGNORECASE,
)


def base_title(title: str) -> str:
    """« Ipséité (Édition Deluxe) » → « ipseite » : clé commune aux éditions."""
    stripped = _EDITION_RE.sub("", title or "").strip() or (title or "")
    decomposed = unicodedata.normalize("NFKD", stripped.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def _date(album: AlbumInfo) -> str:
    return album.release_date or album.year or ""


def newest_first(albums: list[AlbumInfo]) -> list[AlbumInfo]:
    return sorted(albums, key=lambda a: (_date(a), a.track_count or 0), reverse=True)


def split_versions(albums: list[AlbumInfo]) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
    """(albums sans doublon, du plus récent au plus ancien ; autres versions).

    La version gardée est la plus récente (à date égale, la plus fournie)."""
    groups: dict[str, list[AlbumInfo]] = {}
    for album in newest_first(albums):
        key = base_title(album.title)
        groups.setdefault(key or album.uid, []).append(album)
    main = [versions[0] for versions in groups.values()]
    others = [a for versions in groups.values() for a in versions[1:]]
    return newest_first(main), newest_first(others)


def siblings(album: AlbumInfo, catalog: list[AlbumInfo]) -> list[AlbumInfo]:
    """Autres éditions de `album` dans le catalogue de son artiste."""
    key = base_title(album.title)
    return newest_first([a for a in catalog if a.uid != album.uid and base_title(a.title) == key])
