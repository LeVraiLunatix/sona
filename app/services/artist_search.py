from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from app.providers.base import ArtistInfo


def _key(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def rank_artists(query: str, artists: list[ArtistInfo]) -> list[ArtistInfo]:
    """Les homonymes exacts de la requête passent devant, du plus suivi au
    moins suivi — chez Deezer, « ziak » renvoie d'abord un Ziak à 248 fans
    avant celui à 600 000. Le reste garde l'ordre de pertinence de la source
    (qui, lui, gère les fautes de frappe : « eiak » → Ziak)."""
    wanted = _key(query)
    if not wanted:
        return list(artists)
    exact = [a for a in artists if _key(a.name) == wanted]
    exact.sort(key=lambda a: a.fans or 0, reverse=True)
    others = [a for a in artists if _key(a.name) != wanted]
    return exact + others


def name_similarity(query: str, name: str) -> float:
    """Ressemblance 0..1 entre une saisie et un nom d'artiste, sans casse,
    accents ni ponctuation : « eiak » / « Ziak » ≈ 0,75."""
    a, b = _key(query), _key(name)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
