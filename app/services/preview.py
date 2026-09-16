"""Retrouver l'extrait officiel d'un morceau qui n'en a pas.

Sans extrait de 30 s, `audio_match` n'a rien à quoi comparer : Sona envoie
alors ce que le résolveur a choisi, sans preuve que c'est le bon
enregistrement — exactement ce que la vérification acoustique existe pour
éviter. C'est le cas de tous les liens Spotify résolus sans l'API (les données
publiques — oEmbed et page du morceau — donnent l'artiste et la durée, mais ni
ISRC ni extrait), et d'une bonne partie du catalogue Spotify même avec l'API,
`preview_url` y étant souvent nul.

Deezer, lui, publie un extrait pour presque tout son catalogue. On va donc y
chercher le même enregistrement — par ISRC quand on l'a (il identifie
l'enregistrement, pas le titre), sinon par artiste et titre — et on ne reprend
son extrait que si c'est bien le même morceau, avec les mêmes comparaisons que
le résolveur. Vérifier contre le mauvais extrait serait pire que ne pas
vérifier : le bon fichier se ferait rejeter.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerClient, DeezerError
from app.services.resolver import Candidate, rejection_reason

logger = logging.getLogger(__name__)

# Résultats examinés dans la recherche de repli. La recherche simple ramène
# aussi remix, live et reprises avant l'original : dix laissent de la marge,
# au-delà on s'éloigne trop du morceau demandé pour que ce soit encore lui.
SEARCH_LIMIT = 10
_UNKNOWN_ARTISTS = frozenset({"artiste inconnu", "artist inconnu", "unknown artist"})
# « (feat. Pharrell Williams and Nile Rodgers) », « [with X] »…
_FEATURING_RE = re.compile(r"\s*[\(\[](?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]", re.IGNORECASE)


def _as_candidate(track: TrackInfo) -> Candidate:
    """Emballe un morceau Deezer pour le passer aux comparaisons du résolveur.

    `is_song=True` : c'est une fiche de catalogue, pas une vidéo — la
    tolérance de durée appliquée est celle d'une publication officielle.
    """
    return Candidate(
        video_id=f"deezer:{track.source_id}",
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration_seconds=track.duration_seconds,
        cover_url=track.cover_url,
        is_song=True,
    )


def _search_query(track: TrackInfo) -> str | None:
    """Recherche Deezer « artiste principal titre », ou None si l'artiste est inconnu.

    Pas la syntaxe avancée `artist:"…" track:"…"` : Deezer n'y répond plus
    (zéro résultat en septembre 2026, même pour « The Weeknd / Blinding
    Lights »). Une recherche simple ramène aussi remix et live : ce sont les
    contrôles du résolveur qui trient ensuite. Les invités (« feat. … ») et
    les artistes secondaires sont retirés de la requête, Deezer ne les
    écrivant pas forcément comme Spotify.

    Sans nom d'artiste — un lien Spotify dont la page publique n'a pas répondu —
    un titre seul ne prouve rien : « Hasta la Vista » existe chez plusieurs artistes.
    On préfère ne pas vérifier plutôt que de reprendre l'extrait d'un autre.
    """
    if track.artist.strip().lower() in _UNKNOWN_ARTISTS:
        return None
    artist = track.artist.split(",")[0].strip()
    title = _FEATURING_RE.sub("", track.title).strip()
    if not artist or not title:
        return None
    return f"{artist} {title}"


async def _deezer_candidates(deezer: DeezerClient, track: TrackInfo) -> list[TrackInfo]:
    """Morceaux Deezer susceptibles d'être le même enregistrement.

    L'ISRC d'abord : il désigne l'enregistrement exact. La recherche par
    artiste et titre ne sert que s'il manque (lien Spotify résolu par oEmbed)
    ou si l'édition trouvée n'a pas d'extrait.
    """
    candidates: list[TrackInfo] = []
    try:
        if track.isrc:
            found = await deezer.get_track_by_isrc(track.isrc)
            if found is not None:
                candidates.append(found)
        if not any(c.preview_url for c in candidates):
            query = _search_query(track)
            if query is not None:
                items, _total = await deezer.search_tracks(query, limit=SEARCH_LIMIT)
                candidates.extend(items)
    except DeezerError as exc:
        # Deezer en panne : le morceau partira sans vérification, comme avant.
        logger.info("Recherche d'extrait officiel impossible sur Deezer : %s", exc)
    return candidates


async def complete_preview(deezer: DeezerClient, track: TrackInfo) -> TrackInfo:
    """Complète un morceau sans extrait officiel avec celui de Deezer.

    Retourne le morceau inchangé quand il a déjà un extrait, quand il vient de
    Deezer (redemander la même API ne donnerait rien de plus), ou quand aucun
    résultat ne lui correspond assez clairement — mieux vaut envoyer sans
    vérifier que vérifier contre un autre enregistrement.
    """
    if track.preview_url or track.source == "deezer":
        return track

    for match in await _deezer_candidates(deezer, track):
        if not match.preview_url:
            continue
        # Mêmes règles que le résolveur : version dérivée, autre artiste,
        # titre différent, durée trop éloignée. Un ISRC peut mener à une
        # réédition, et une recherche à un homonyme.
        refus = rejection_reason(track, _as_candidate(match))
        if refus is None:
            logger.info(
                "Extrait officiel repris de Deezer %s pour %s — %s (par %s)",
                match.source_id, track.artist, track.title,
                "ISRC" if track.isrc else "artiste et titre",
            )
            return replace(
                track,
                preview_url=match.preview_url,
                duration_seconds=match.duration_seconds or track.duration_seconds,
            )
        logger.info(
            "Extrait Deezer %s écarté pour %s — %s : %s",
            match.source_id, track.artist, track.title, refus,
        )

    logger.info(
        "Aucun extrait officiel pour %s — %s (%s) : envoi sans vérification acoustique",
        track.artist, track.title, track.source,
    )
    return track
