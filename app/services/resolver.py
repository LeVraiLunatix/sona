from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import yt_dlp
from ytmusicapi import YTMusic

from app.logging_config import ytdlp_logger
from app.providers.base import ArtistInfo, TrackInfo
from app.providers.youtube import YoutubeError
from app.services.artwork import DISPLAY_SIZE, resize_artwork_url

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


def _word_re(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)")


# Versions qui ne sont pas l'enregistrement demandé. YouTube en regorge sous
# des titres quasi identiques (« PNL - Au DD (INSTRUMENTAL) ») : on ne les
# retient jamais, sauf si le morceau de référence en est lui-même une
# (« Summer (… Remix) », « Bohemian Rhapsody (Live Aid) »).
_DERIVATIVE_VERSIONS: dict[str, re.Pattern[str]] = {
    "instrumental": _word_re(r"instrumental|instru|karaoke|type\s*beat"),
    "remix": _word_re(r"remix|rmx|bootleg|mashup"),
    "accéléré/ralenti": _word_re(r"slowed|reverb|sped\s+up|speed\s+up|nightcore|8d|bass\s+boosted"),
    "reprise": _word_re(r"cover|reprise"),
    "acoustique": _word_re(r"acoustic|acoustique|unplugged"),
    "live": _word_re(r"live|concert"),
    "version longue": _word_re(r"extended|club\s+mix"),
    "a cappella": _word_re(r"a\s*cappella|acapella|vocals?\s+only|drumless"),
    "lo-fi": _word_re(r"lo\s*fi"),
    "hauteur modifiée": _word_re(r"\d{3}\s*hz"),
    "hors musique": _word_re(r"making\s+of|reaction|react|tutorial|tuto|lesson|amv|backing\s+track|back\s+track"),
}
# Même audio, mais une mise en ligne secondaire : départage seulement.
_SECONDARY_UPLOAD_RE = _word_re(r"lyrics?|paroles|letra|tradu\w*|translat\w*")
_FEAT_WORD_RE = _word_re(r"feat|ft|featuring")
_ARTIST_SEPARATOR_RE = re.compile(r"\s*(?:,|&|\+|/|\bx\b|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.IGNORECASE)
# Mots qui habillent un titre YouTube sans rien dire du morceau.
_FILLER_WORDS = frozenset(
    "official officiel officielle video clip music musique audio lyrics lyric paroles "
    "letra visualizer hd hq 4k by ft featuring topic vevo".split()
)
_UNKNOWN_ARTISTS = frozenset({"artiste inconnu"})
# Suffixes des chaînes officielles : « Queen Official », « DaftPunkVEVO », « PNL - Topic ».
_CHANNEL_SUFFIX_RE = re.compile(r"(?:\s*(?:official|officiel|officielle|music|musique|topic|vevo))+$")

# Un score en dessous duquel on considère que le résultat n'a rien à voir.
ACCEPT_SCORE = 0.35
# Titre minimum pour qu'un résultat soit seulement envisagé.
ACCEPT_TITLE_SIMILARITY = 0.72
# Nom de chaîne assez proche du nom d'artiste pour être la même personne.
ARTIST_SIMILARITY = 0.75
# Écart de durée toléré. Un repost de l'audio original tombe à 2-3 s près ;
# au-delà, c'est une autre version : clip avec intro, instru recoupée,
# audio accéléré pour échapper au Content ID…
DURATION_TOLERANCE = 7
DURATION_TOLERANCE_RATIO = 0.03
# Un titre publié par l'artiste lui-même peut s'écarter un peu plus (silence
# final, autre mastering) sans être un autre enregistrement.
OFFICIAL_DURATION_TOLERANCE = 15
OFFICIAL_DURATION_TOLERANCE_RATIO = 0.08
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
    platform: str = "youtube"  # "youtube" | "soundcloud"
    url: str | None = None
    # Identifiant YouTube Music de l'artiste principal (`artists[0].id` dans
    # la réponse `ytmusicapi`) : permet d'ouvrir une vraie fiche artiste
    # (voir `get_artist_info`) pour un morceau qui n'existe que là — Deezer,
    # Apple et Spotify ont leur propre identifiant d'artiste, YouTube brut
    # (yt-dlp) n'en a aucun, mais YouTube Music, si.
    artist_id: str | None = None

    @property
    def source_url(self) -> str:
        """Adresse à passer à yt-dlp pour télécharger ce candidat."""
        return self.url or f"https://www.youtube.com/watch?v={self.video_id}"


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


def _plain(text: str) -> str:
    """Minuscules sans accents ni ponctuation, pour repérer des mots entiers."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_PUNCT_RE.sub(" ", text).split())


def _mentions(text: str, phrase: str) -> bool:
    """`phrase` apparaît dans `text` en mots entiers : « menace » ne doit pas
    se retrouver dans « menacesantana »."""
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _version_labels(*texts: str | None) -> set[str]:
    plain = _plain(" ".join(t for t in texts if t))
    return {label for label, pattern in _DERIVATIVE_VERSIONS.items() if pattern.search(plain)}


def derivative_labels(track: TrackInfo, candidate: Candidate) -> set[str]:
    """Types de version dérivée du candidat que le morceau de référence n'a pas."""
    return _version_labels(candidate.title, candidate.album) - _version_labels(track.title, track.album)


def _artist_names(track: TrackInfo) -> list[str]:
    names = [_plain(track.artist)]
    names += [_plain(part) for part in _ARTIST_SEPARATOR_RE.split(track.artist)]
    return [n for n in dict.fromkeys(names) if n and n not in _UNKNOWN_ARTISTS]


def _channel_names(candidate: Candidate) -> list[str]:
    parts = [candidate.artist, *_ARTIST_SEPARATOR_RE.split(candidate.artist)]
    names = (_CHANNEL_SUFFIX_RE.sub("", _plain(part)).strip() for part in parts)
    return [n for n in dict.fromkeys(names) if n]


def _is_by_artist(track: TrackInfo, candidate: Candidate) -> bool:
    """La chaîne / l'artiste du résultat est l'artiste du morceau.

    Le nom doit être celui de l'artiste, pas seulement le contenir : « PNL
    SPAIN » est une chaîne de fans, alors que « Queen Official » ou
    « DaftPunkVEVO » sont bien les chaînes des artistes.
    """
    return any(
        channel == name or SequenceMatcher(None, name, channel).ratio() >= ARTIST_SIMILARITY
        for name in _artist_names(track)
        for channel in _channel_names(candidate)
    )


def artist_matches(track: TrackInfo, candidate: Candidate) -> bool:
    """L'artiste est là, dans le champ artiste ou dans le titre de la vidéo
    (« Artiste - Titre » publié par une chaîne tierce). Un même titre chanté
    par quelqu'un d'autre (« Hasta la Vista » de MC Solaar) est un autre morceau."""
    names = _artist_names(track)
    if not names:
        return True
    title = _plain(candidate.title)
    return _is_by_artist(track, candidate) or any(_mentions(title, name) for name in names)


def _duration_gap(track: TrackInfo, candidate: Candidate) -> int | None:
    if not track.duration_seconds or not candidate.duration_seconds:
        return None
    return abs(track.duration_seconds - candidate.duration_seconds)


def _duration_ok(track: TrackInfo, candidate: Candidate) -> bool:
    gap = _duration_gap(track, candidate)
    if gap is None:
        return True
    if candidate.is_song and _is_by_artist(track, candidate):
        allowed = max(OFFICIAL_DURATION_TOLERANCE, track.duration_seconds * OFFICIAL_DURATION_TOLERANCE_RATIO)
    else:
        allowed = max(DURATION_TOLERANCE, track.duration_seconds * DURATION_TOLERANCE_RATIO)
    return gap <= allowed


def _extra_words(track: TrackInfo, candidate: Candidate) -> int:
    """Mots du titre YouTube qui ne viennent ni du titre, ni de l'artiste, ni
    de l'habillage habituel : « AU DIKI - MC LAMA (PNL - AU DD version DZ) »
    contient bien « au dd », mais c'est une parodie."""
    def words(text: str) -> set[str]:
        return set(_plain(_normalize(text)).split())

    known = words(track.title) | words(track.artist) | _FILLER_WORDS
    return len(words(candidate.title) - known)


def title_similarity(track: TrackInfo, candidate: Candidate) -> float:
    ref, cand = _normalize(track.title), _normalize(candidate.title)
    best = SequenceMatcher(None, ref, cand).ratio()
    # Sur YouTube le titre est souvent "Artiste - Titre (Official Video)" :
    # comparer aussi le noyau des deux titres évite de rater la correspondance.
    core_ref, core_cand = _core_title(track.title), _core_title(candidate.title)
    best = max(best, SequenceMatcher(None, core_ref, core_cand).ratio())
    if _mentions(cand, core_ref):
        best = max(best, 0.9 - 0.05 * max(0, _extra_words(track, candidate) - 1))
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
    if _is_by_artist(track, candidate):
        # Publié par l'artiste : préférable à un repost du même audio.
        score += 0.05

    candidate_title, reference_title = _plain(candidate.title), _plain(track.title)
    if _SECONDARY_UPLOAD_RE.search(candidate_title) and not _SECONDARY_UPLOAD_RE.search(reference_title):
        score -= 0.05
    if _FEAT_WORD_RE.search(candidate_title) and not _FEAT_WORD_RE.search(reference_title):
        # « Alors On Danse (Featuring Erik Hassle) » : une autre version.
        score -= 0.1

    return score


def rejection_reason(track: TrackInfo, candidate: Candidate) -> str | None:
    """Pourquoi un résultat ne peut pas être envoyé, ou None s'il le peut."""
    derived = derivative_labels(track, candidate)
    if derived:
        return "version dérivée (" + ", ".join(sorted(derived)) + ")"
    if not artist_matches(track, candidate):
        return "autre artiste"
    if title_similarity(track, candidate) < ACCEPT_TITLE_SIMILARITY:
        return "titre différent"
    if not _duration_ok(track, candidate):
        return "durée trop éloignée"
    return None


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
    artists = item.get("artists") or []
    return Candidate(
        video_id=video_id,
        title=item.get("title") or "",
        artist=", ".join(a.get("name", "") for a in artists),
        album=album.get("name") if isinstance(album, dict) else None,
        duration_seconds=item.get("duration_seconds"),
        # YouTube Music ne renvoie que des vignettes de 60 et 120 px.
        cover_url=resize_artwork_url(thumbnails[-1]["url"], DISPLAY_SIZE) if thumbnails else None,
        is_song=item.get("resultType") == "song",
        artist_id=artists[0].get("id") if artists else None,
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


def rank_candidates(track: TrackInfo, candidates: list[Candidate]) -> list[Candidate]:
    """Candidats acceptables, du plus probable au moins probable.

    Mieux vaut « aucune source » qu'un autre enregistrement : quand l'original
    n'est pas sur YouTube, les résultats restants sont des instrus, remixes ou
    homonymes, et l'utilisateur recevrait autre chose que ce qu'il a demandé.
    """

    def rank(c: Candidate) -> tuple[float, int]:
        # À score égal, la durée la plus proche : c'est le meilleur indice
        # qu'il s'agit du même enregistrement.
        gap = _duration_gap(track, c)
        return score_candidate(track, c), -(gap if gap is not None else 10_000)

    eligible = [
        c for c in candidates if rejection_reason(track, c) is None and score_candidate(track, c) >= ACCEPT_SCORE
    ]
    return sorted(eligible, key=rank, reverse=True)


def select_best(track: TrackInfo, candidates: list[Candidate]) -> Candidate | None:
    """Meilleur candidat acceptable, ou None si aucun ne ressemble au morceau."""
    ranked = rank_candidates(track, candidates)
    return ranked[0] if ranked else None


def _candidate_from_soundcloud(entry: dict) -> Candidate | None:
    track_id = entry.get("id")
    url = entry.get("webpage_url") or entry.get("url")
    if not track_id or not url:
        return None
    duration = entry.get("duration")
    thumbnails = entry.get("thumbnails") or []
    return Candidate(
        video_id=f"soundcloud:{track_id}",
        title=entry.get("title") or "",
        artist=entry.get("uploader") or "",
        album=None,
        duration_seconds=round(duration) if duration else None,
        cover_url=thumbnails[-1].get("url") if thumbnails else None,
        is_song=False,
        platform="soundcloud",
        url=url,
    )


def _search_soundcloud_sync(query: str) -> list[Candidate]:
    """Recherche SoundCloud via `yt-dlp`, sans cookies.

    Certains artistes y publient eux-mêmes des titres absents de YouTube
    (l'album « Deux frères » de PNL). Les titres protégés par DRM y figurent
    aussi : yt-dlp refuse de les télécharger, et ils sont alors sautés.
    """
    opts = {
        "quiet": True,
        "logger": ytdlp_logger,
        "skip_download": True,
        "extract_flat": True,
        "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"scsearch{SEARCH_LIMIT}:{query}", download=False)
    except Exception as exc:
        logger.warning("Recherche SoundCloud échouée pour %r: %s", query, exc)
        return []
    entries = (data or {}).get("entries") or []
    return [c for c in (_candidate_from_soundcloud(e) for e in entries if e) if c]


def _log_choice(track: TrackInfo, best: Candidate | None, candidates: list[Candidate]) -> None:
    if best is not None:
        logger.info(
            "Source %s pour %s — %s (%ss) : %s « %s » par %s (%ss, score %.2f)",
            best.platform, track.artist, track.title, track.duration_seconds, best.video_id, best.title,
            best.artist, best.duration_seconds, score_candidate(track, best),
        )
        return
    closest = sorted(candidates, key=lambda c: score_candidate(track, c), reverse=True)[:3]
    logger.info(
        "Aucun des %d résultats ne convient pour %s — %s : %s",
        len(candidates), track.artist, track.title,
        "; ".join(
            f"{c.video_id} « {c.title} » ({rejection_reason(track, c) or 'score trop bas'})" for c in closest
        )
        or "aucun résultat",
    )


async def iter_audio_sources(track: TrackInfo, cookies_file: Path | None = None) -> AsyncIterator[Candidate]:
    """Sources audio acceptables d'un morceau, de la plus probable à la moins probable.

    L'appelant télécharge chaque source, la compare à l'extrait officiel et
    s'arrête au bout de quelques essais : l'ordre compte. Viennent donc
    1. le meilleur titre publié par l'artiste sur YouTube Music ;
    2. les publications de l'artiste sur SoundCloud, où certains mettent des
       titres absents de YouTube ;
    3. les autres résultats YouTube Music (reposts), puis SoundCloud ;
    4. la recherche YouTube de `yt-dlp`, en dernier recours.
    Chaque recherche n'est lancée qu'une fois les sources précédentes
    épuisées. Lève ResolutionError si aucun moteur ne répond.
    """
    if track.source == "youtube":
        yield Candidate(
            video_id=track.source_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_seconds=track.duration_seconds,
            cover_url=track.cover_url,
            is_song=False,
        )
        return

    queries = _query_variants(track)
    candidates = await asyncio.to_thread(_search_ytmusic_sync, queries)
    youtube_music = rank_candidates(track, candidates)
    offered: set[str] = set()

    def offer(candidate: Candidate) -> bool:
        if candidate.video_id in offered:
            return False
        offered.add(candidate.video_id)
        _log_choice(track, candidate, candidates)
        return True

    for candidate in [c for c in youtube_music if _is_by_artist(track, c)][:1]:
        if offer(candidate):
            yield candidate

    soundcloud_results = await asyncio.to_thread(_search_soundcloud_sync, queries[0])
    candidates.extend(soundcloud_results)
    soundcloud = rank_candidates(track, soundcloud_results)
    for candidate in soundcloud:
        if _is_by_artist(track, candidate) and offer(candidate):
            yield candidate
    for candidate in youtube_music + soundcloud:
        if offer(candidate):
            yield candidate

    logger.info("Plus de source YouTube Music ni SoundCloud pour %r — repli sur la recherche yt-dlp", queries[0])
    for query in queries[:2]:
        fallback = await asyncio.to_thread(_search_ytdlp_sync, query, cookies_file)
        candidates.extend(fallback)
        for candidate in rank_candidates(track, fallback):
            if offer(candidate):
                yield candidate

    if not candidates:
        raise ResolutionError("Recherche de la source impossible.")
    if not offered:
        _log_choice(track, None, candidates)


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
                artist_source_id=candidate.artist_id,
            )
        )
    return tracks


def _get_artist_sync(channel_id: str) -> dict:
    return _ytmusic().get_artist(channel_id)


def _track_from_ytmusic_song(item: dict, fallback_artist: str, artist_id: str) -> TrackInfo | None:
    video_id = item.get("videoId")
    if not video_id:
        return None
    thumbnails = item.get("thumbnails") or []
    album = item.get("album")
    artists = item.get("artists") or []
    return TrackInfo(
        source="youtube",
        source_id=video_id,
        title=item.get("title") or "Titre inconnu",
        artist=", ".join(a.get("name", "") for a in artists) or fallback_artist,
        album=album.get("name") if isinstance(album, dict) else None,
        year=None,
        duration_seconds=item.get("duration_seconds"),
        cover_url=resize_artwork_url(thumbnails[-1]["url"], DISPLAY_SIZE) if thumbnails else None,
        # `artists[0].id` peut être un featuring plutôt que l'artiste de cette
        # fiche : à défaut, l'identifiant de la fiche elle-même reste un
        # meilleur repère que rien.
        artist_source_id=artists[0].get("id") if artists and artists[0].get("id") else artist_id,
    )


async def get_artist_info(channel_id: str) -> ArtistInfo:
    """Fiche artiste YouTube Music : nom + photo, à partir de son
    `channelId` (glané dans `artists[0].id` d'un résultat de recherche —
    voir `Candidate.artist_id`). YouTube (brut, `yt-dlp`) n'a pas cette
    notion, seule YouTube Music (`ytmusicapi`) en a une exploitable ici."""
    try:
        data = await asyncio.to_thread(_get_artist_sync, channel_id)
    except Exception as exc:
        raise YoutubeError("Artiste YouTube Music introuvable.") from exc
    thumbnails = data.get("thumbnails") or []
    return ArtistInfo(
        source="youtube",
        source_id=channel_id,
        name=data.get("name") or "Artiste inconnu",
        picture_url=thumbnails[-1]["url"] if thumbnails else None,
    )


async def get_artist_top_tracks_youtube(channel_id: str, limit: int = 25) -> list[TrackInfo]:
    try:
        data = await asyncio.to_thread(_get_artist_sync, channel_id)
    except Exception as exc:
        raise YoutubeError("Artiste YouTube Music introuvable.") from exc
    name = data.get("name") or "Artiste inconnu"
    songs = (data.get("songs") or {}).get("results") or []
    tracks = []
    for item in songs[:limit]:
        track = _track_from_ytmusic_song(item, name, channel_id)
        if track:
            tracks.append(track)
    return tracks


def _search_tracks_ytdlp_sync(query: str, limit: int) -> list[TrackInfo]:
    """Dernier repli de la recherche texte, quand YouTube Music lui-même ne
    trouve rien : la recherche YouTube "brute" (le moteur Google général,
    pas l'index structuré de YouTube Music) tolère mieux les requêtes
    tronquées ou mal orthographiées (ex: un nom d'artiste sans sa première
    lettre) — au prix de métadonnées plus pauvres (pas toujours d'identifiant
    de chaîne, pas d'album)."""
    opts = {
        "quiet": True,
        "logger": ytdlp_logger,
        "skip_download": True,
        "extract_flat": True,
        "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        logger.warning("Recherche YouTube (yt-dlp) échouée pour %r: %s", query, exc)
        return []
    tracks: list[TrackInfo] = []
    for entry in (data or {}).get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        thumbnails = entry.get("thumbnails") or []
        tracks.append(
            TrackInfo(
                source="youtube",
                source_id=entry["id"],
                title=entry.get("title") or "Titre inconnu",
                artist=entry.get("channel") or entry.get("uploader") or "Chaîne inconnue",
                album=None,
                year=None,
                duration_seconds=int(entry["duration"]) if entry.get("duration") else None,
                cover_url=thumbnails[-1]["url"] if thumbnails else None,
                artist_source_id=entry.get("channel_id") or entry.get("uploader_id"),
            )
        )
    return tracks


async def search_tracks_youtube_raw(query: str, limit: int = 20) -> list[TrackInfo]:
    return await asyncio.to_thread(_search_tracks_ytdlp_sync, query, limit)


async def search_tracks_youtube(query: str, limit: int = 20) -> list[TrackInfo]:
    """Recherche de morceaux sur YouTube Music (dernier recours de la
    recherche textuelle, quand Deezer et iTunes sont muets)."""
    return await asyncio.to_thread(_search_tracks_youtube_sync, query, limit)
