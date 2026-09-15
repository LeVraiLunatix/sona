from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import yt_dlp
from ytmusicapi import YTMusic

from app.logging_config import ytdlp_logger
from app.providers.base import TrackInfo

logger = logging.getLogger(__name__)

_FEAT_RE = re.compile(r"\(feat\.?[^)]*\)|\[feat\.?[^\]]*\]|feat\.?.*$", re.IGNORECASE)
_PARENS_RE = re.compile(r"\((?:[^)]*)\)|\[[^\]]*\]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
# Mentions de version/remaster qui n'existent pas forcément côté YouTube et
# font chuter la similarité alors que c'est bien le même morceau.
_NOISE_RE = re.compile(
    r"\b(remaster(ed)?|radio edit|album version|single version|explicit|clean|"
    r"official (music )?video|lyric video|audio|hd|hq|mono|stereo|bonus track)\b"
    r"|\b\d{4} (remaster|version)\b",
    re.IGNORECASE,
)

# Un score en dessous duquel on considère que le résultat n'a rien à voir.
ACCEPT_SCORE = 0.35
# Repli : même si le score global est faible (artiste mal renseigné côté
# YouTube, chaîne au lieu du nom d'artiste…), un titre qui correspond
# vraiment suffit à envoyer l'audio plutôt qu'un « indisponible ».
ACCEPT_TITLE_SIMILARITY = 0.72
# Nombre de résultats demandés à chaque recherche.
SEARCH_LIMIT = 8


class ResolutionError(Exception):
    pass


@dataclass(slots=True)
class Candidate:
    video_id: str
    title: str
    artist: str
    album: str | None
    duration_seconds: int | None
    cover_url: str | None
    is_song: bool


@lru_cache(maxsize=1)
def _ytmusic() -> YTMusic:
    return YTMusic()


def _normalize(text: str) -> str:
    text = _FEAT_RE.sub("", text)
    text = _NOISE_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text.lower())
    return " ".join(text.split())


def _core_title(title: str) -> str:
    """Titre débarrassé de ses parenthèses (versions, remixes, "feat.")."""
    stripped = _PARENS_RE.sub(" ", title)
    return _normalize(stripped) or _normalize(title)


def title_similarity(track: TrackInfo, candidate: Candidate) -> float:
    ref, cand = _normalize(track.title), _normalize(candidate.title)
    best = SequenceMatcher(None, ref, cand).ratio()
    # Sur YouTube le titre est souvent "Artiste - Titre (Official Video)" :
    # comparer aussi le noyau des deux titres évite de rater la correspondance.
    core_ref, core_cand = _core_title(track.title), _core_title(candidate.title)
    best = max(best, SequenceMatcher(None, core_ref, core_cand).ratio())
    if core_ref and core_ref in cand:
        best = max(best, 0.9)
    return best


def score_candidate(track: TrackInfo, candidate: Candidate) -> float:
    title_sim = title_similarity(track, candidate)
    artist_sim = SequenceMatcher(
        None, _normalize(track.artist), _normalize(candidate.artist)
    ).ratio()
    if _normalize(track.artist) and _normalize(track.artist) in _normalize(candidate.title):
        # "Artiste - Titre" dans le titre de la vidéo : l'artiste est bien là,
        # même si le champ artiste du résultat est un nom de chaîne.
        artist_sim = max(artist_sim, 0.8)

    score = title_sim * 0.6 + artist_sim * 0.4

    if track.duration_seconds and candidate.duration_seconds:
        diff = abs(track.duration_seconds - candidate.duration_seconds)
        if diff <= 3:
            score += 0.15
        elif diff <= 8:
            score += 0.05
        elif diff > 20:
            score -= 0.2

    if candidate.is_song:
        score += 0.05

    return score


def _query_variants(track: TrackInfo) -> list[str]:
    """Plusieurs formulations : une seule requête rate régulièrement un
    morceau que YouTube Music connaît pourtant sous un libellé voisin."""
    title, artist = track.title.strip(), track.artist.strip()
    core = _PARENS_RE.sub(" ", title).strip()
    core = " ".join(core.split())
    variants = [f"{artist} {title}"]
    if core and core.lower() != title.lower():
        variants.append(f"{artist} {core}")
    if track.album:
        variants.append(f"{artist} {title} {track.album}")
    variants.append(title)
    seen: set[str] = set()
    ordered = []
    for variant in variants:
        cleaned = " ".join(variant.split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            ordered.append(cleaned)
    return ordered


def _candidate_from_ytmusic(item: dict) -> Candidate | None:
    video_id = item.get("videoId")
    if not video_id:
        return None
    thumbnails = item.get("thumbnails") or []
    album = item.get("album")
    return Candidate(
        video_id=video_id,
        title=item.get("title") or "",
        artist=", ".join(a.get("name", "") for a in item.get("artists") or []),
        album=album.get("name") if isinstance(album, dict) else None,
        duration_seconds=item.get("duration_seconds"),
        cover_url=thumbnails[-1]["url"] if thumbnails else None,
        is_song=item.get("resultType") == "song",
    )


def _search_ytmusic_sync(queries: list[str]) -> list[Candidate]:
    yt = _ytmusic()
    found: dict[str, Candidate] = {}
    for query in queries:
        for search_filter in ("songs", "videos"):
            try:
                results = yt.search(query, filter=search_filter, limit=SEARCH_LIMIT)
            except Exception as exc:
                logger.warning("YouTube Music (%s) a échoué sur %r: %s", search_filter, query, exc)
                continue
            for item in results or []:
                candidate = _candidate_from_ytmusic(item)
                if candidate and candidate.video_id not in found:
                    found[candidate.video_id] = candidate
    return list(found.values())


def _search_ytdlp_sync(query: str, cookies_file: Path | None) -> list[Candidate]:
    """Repli quand `ytmusicapi` ne trouve rien (ou est en panne).

    Passe par la recherche YouTube de `yt-dlp`, qui emprunte exactement le
    même chemin que le téléchargement — si elle répond, le morceau est
    téléchargeable."""
    opts = {
        "quiet": True,
        # Plutôt que `no_warnings` : les avertissements utiles remontent.
        "logger": ytdlp_logger,
        "skip_download": True,
        "extract_flat": True,
        "socket_timeout": 20,
    }
    if cookies_file is not None:
        opts["cookiefile"] = str(cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{SEARCH_LIMIT}:{query}", download=False)
    except Exception as exc:
        logger.warning("Recherche yt-dlp échouée pour %r: %s", query, exc)
        return []

    candidates = []
    for entry in (data or {}).get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        duration = entry.get("duration")
        candidates.append(
            Candidate(
                video_id=entry["id"],
                title=entry.get("title") or "",
                artist=entry.get("channel") or entry.get("uploader") or "",
                album=None,
                duration_seconds=int(duration) if duration else None,
                cover_url=(entry.get("thumbnails") or [{}])[-1].get("url"),
                is_song=False,
            )
        )
    return candidates


def select_best(track: TrackInfo, candidates: list[Candidate]) -> Candidate | None:
    """Meilleur candidat acceptable, ou None si aucun ne ressemble au morceau."""
    if not candidates:
        return None
    best = max(candidates, key=lambda c: score_candidate(track, c))
    if score_candidate(track, best) >= ACCEPT_SCORE:
        return best
    by_title = max(candidates, key=lambda c: title_similarity(track, c))
    if title_similarity(track, by_title) >= ACCEPT_TITLE_SIMILARITY:
        return by_title
    return None


def _matched_track(track: TrackInfo, candidate: Candidate) -> TrackInfo:
    return TrackInfo(
        source="youtube",
        source_id=candidate.video_id,
        title=candidate.title or track.title,
        artist=candidate.artist or track.artist,
        album=candidate.album,
        year=None,
        duration_seconds=candidate.duration_seconds or track.duration_seconds,
        cover_url=candidate.cover_url or track.cover_url,
    )


async def find_youtube_match(
    track: TrackInfo, cookies_file: Path | None = None
) -> tuple[str, TrackInfo] | None:
    """Cherche le meilleur équivalent YouTube pour un morceau.

    Deux moteurs sont interrogés en cascade : YouTube Music (métadonnées
    propres, mais catalogue incomplet et API non officielle qui tombe en
    panne) puis la recherche YouTube de `yt-dlp`. Retourne
    `(video_id, TrackInfo)` ou None si rien ne correspond vraiment.
    """
    if track.source == "youtube":
        return track.source_id, track

    queries = _query_variants(track)

    candidates = await asyncio.to_thread(_search_ytmusic_sync, queries)
    best = select_best(track, candidates)
    if best is not None:
        return best.video_id, _matched_track(track, best)

    logger.info(
        "Aucune correspondance YouTube Music pour %r — repli sur la recherche yt-dlp",
        queries[0],
    )
    for query in queries[:2]:
        fallback = await asyncio.to_thread(_search_ytdlp_sync, query, cookies_file)
        if not fallback:
            continue
        candidates.extend(fallback)
        best = select_best(track, candidates)
        if best is not None:
            return best.video_id, _matched_track(track, best)

    if not candidates:
        raise ResolutionError("Recherche de la source impossible.")
    return None


def _search_tracks_youtube_sync(query: str, limit: int) -> list[TrackInfo]:
    yt = _ytmusic()
    try:
        results = yt.search(query, filter="songs", limit=limit)
    except Exception as exc:
        logger.warning("Recherche YouTube Music échouée pour %r: %s", query, exc)
        return []
    tracks = []
    for item in results or []:
        candidate = _candidate_from_ytmusic(item)
        if candidate is None:
            continue
        tracks.append(
            TrackInfo(
                source="youtube",
                source_id=candidate.video_id,
                title=candidate.title,
                artist=candidate.artist or "Artiste inconnu",
                album=candidate.album,
                year=None,
                duration_seconds=candidate.duration_seconds,
                cover_url=candidate.cover_url,
            )
        )
    return tracks


async def search_tracks_youtube(query: str, limit: int = 20) -> list[TrackInfo]:
    """Recherche de morceaux sur YouTube Music (dernier recours de la
    recherche textuelle, quand Deezer et iTunes sont muets)."""
    return await asyncio.to_thread(_search_tracks_youtube_sync, query, limit)
