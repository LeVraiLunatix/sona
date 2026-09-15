import asyncio

import pytest

from app.providers.base import TrackInfo
from app.services import resolver
from app.services.resolver import (
    Candidate,
    _query_variants,
    rejection_reason,
    score_candidate,
    select_best,
    title_similarity,
)


def track(title="Instant Crush", artist="Daft Punk", album="Random Access Memories", duration=337):
    return TrackInfo(
        source="deezer",
        source_id="1",
        title=title,
        artist=artist,
        album=album,
        year="2013",
        duration_seconds=duration,
        cover_url=None,
    )


def candidate(title, artist, duration=337, is_song=True, video_id="v"):
    return Candidate(
        video_id=video_id,
        title=title,
        artist=artist,
        album=None,
        duration_seconds=duration,
        cover_url=None,
        is_song=is_song,
    )


def test_query_variants_cover_several_formulations():
    variants = _query_variants(track(title="Instant Crush (feat. Julian Casablancas)"))
    assert variants[0] == "Daft Punk Instant Crush (feat. Julian Casablancas)"
    # Le titre sans sa parenthèse : YouTube Music le référence souvent ainsi.
    assert "Daft Punk Instant Crush" in variants
    assert len(variants) == len(set(variants))


def test_exact_match_wins_over_unrelated_result():
    best = select_best(
        track(),
        [
            candidate("Une chanson sans rapport", "Autre Artiste", duration=120, video_id="a"),
            candidate("Instant Crush", "Daft Punk", video_id="b"),
        ],
    )
    assert best.video_id == "b"


def test_youtube_style_title_is_recognised():
    """Titre « Artiste - Titre (Official Video) » avec une chaîne VEVO comme
    artiste : c'est le cas le plus courant des résultats vidéo, il ne doit
    pas être rejeté."""
    cand = candidate("Daft Punk - Instant Crush (Official Video)", "DaftPunkVEVO", is_song=False)
    assert title_similarity(track(), cand) > 0.7
    assert select_best(track(), [cand]) is not None


def test_remaster_mention_does_not_break_the_match():
    cand = candidate("Instant Crush", "Daft Punk")
    assert select_best(track(title="Instant Crush (2013 Remaster)"), [cand]) is not None


def test_unrelated_results_are_rejected():
    candidates = [
        candidate("Recette de crêpes", "Cuisine TV", duration=90, is_song=False, video_id="x"),
        candidate("Tutoriel guitare", "Prof", duration=600, is_song=False, video_id="y"),
    ]
    assert select_best(track(), candidates) is None


def test_duration_mismatch_is_penalised():
    close = candidate("Instant Crush", "Daft Punk", duration=337, video_id="close")
    far = candidate("Instant Crush", "Daft Punk", duration=90, video_id="far")
    assert score_candidate(track(), close) > score_candidate(track(), far)
    assert select_best(track(), [far, close]).video_id == "close"


def test_no_candidates_returns_none():
    assert select_best(track(), []) is None


def pnl(title, duration, album="Deux frères"):
    return track(title=title, artist="PNL", album=album, duration=duration)


def test_instrumental_of_the_track_is_never_sent():
    """Cas réel : « PNL — Au DD » était résolu vers « PNL - Au DD (INSTRUMENTAL) »."""
    best = select_best(
        pnl("Au DD", 247, album="Au DD"),
        [
            candidate("PNL - Au DD (INSTRUMENTAL)", "JeromeK Prod.", 245, is_song=False, video_id="instru"),
            candidate(
                "PNL – Au DD (Instrumental TypeBeat by Chipmunks Denzel)", "Chipmunks Denzel", 244,
                is_song=False, video_id="typebeat",
            ),
            candidate("AU DIKI - MC LAMA (PNL - AU DD version DZ)", "Adel Sweezy", 246, is_song=False, video_id="parodie"),
            candidate("PNL - Au DD (Paroles/lyrics)", "Et Dieu créa les femmes", 245, is_song=False, video_id="paroles"),
        ],
    )
    assert best.video_id == "paroles"


def test_no_source_rather_than_another_recording():
    """Cas réel : « Hasta la vista » n'a pas de version officielle sur YouTube.
    L'« Audio Officiel » d'une chaîne tierce était l'instru (17 s de trop), et
    le seul titre à la bonne durée est un homonyme de MC Solaar."""
    assert (
        select_best(
            pnl("Hasta la vista", 216),
            [
                candidate("PNL - HASTA LA VISTA (Audio Officiel)", "Heuss L'enfoiré", 233, is_song=False, video_id="instru"),
                candidate("Hasta la Vista", "MC Solaar", 219, is_song=False, video_id="homonyme"),
                candidate(
                    "PNL - Hasta La Vista 2 (Keyzer Remix) + paroles", "Keyzer Prod", 196,
                    is_song=False, video_id="remix",
                ),
                candidate(
                    '[FREE] Summer Raggaeton Type Beat | PNL Type Beat | "Hasta la vista"', "BARTH BEATS", 236,
                    is_song=False, video_id="beat",
                ),
            ],
        )
        is None
    )


def test_instrumental_song_does_not_tie_with_the_original():
    """Nekfeu publie aussi « On verra (Instrumental) », à la même durée :
    l'ordre des résultats ne doit pas décider."""
    ref = track(title="On verra", artist="Nekfeu", album="Feu", duration=211)
    best = select_best(
        ref,
        [
            candidate("On verra (Instrumental)", "Nekfeu", 212, video_id="instru"),
            candidate("On verra", "Nekfeu", 212, video_id="original"),
        ],
    )
    assert best.video_id == "original"


def test_version_named_in_the_reference_is_accepted():
    ref = track(
        title="Summer (R3hab & Ummet Ozcan Remix)", artist="Calvin Harris", album="Summer (Remixes)", duration=280
    )
    best = select_best(
        ref,
        [
            candidate("Summer (Extended Mix)", "Calvin Harris", 297, video_id="extended"),
            candidate("Summer (R3hab & Ummet Ozcan Remix)", "Calvin Harris", 281, video_id="remix"),
        ],
    )
    assert best.video_id == "remix"


def test_title_must_match_whole_words():
    """« Menace » n'est pas « Haki ft Ziak, MenaceSantana »."""
    cand = candidate("PNL - Haki ft Ziak,MenaceSantana(prod: Haki)", "Aïko_", 183, is_song=False)
    assert rejection_reason(pnl("Menace", 188), cand) == "titre différent"


def test_same_title_by_another_artist_is_rejected():
    ref = track(title="Get Lucky", artist="Daft Punk", duration=248)
    assert rejection_reason(ref, candidate("Get Lucky", "Funk Punk", 250)) == "autre artiste"


def test_pitch_shifted_upload_is_rejected():
    ref = track(title="Alors on danse (Radio Edit)", artist="Stromae", album="Cheese", duration=208)
    cand = candidate("Stromae - Alors on danse (Radio Edit) (639Hz)", "SpookEYe47", 207, is_song=False)
    assert rejection_reason(ref, cand).startswith("version dérivée")


def test_one_of_several_credited_artists_is_enough():
    """Spotify liste tous les artistes (« Daft Punk, Pharrell Williams ») alors
    que la chaîne ne porte que le premier."""
    ref = track(title="Get Lucky", artist="Daft Punk, Pharrell Williams", duration=248)
    assert select_best(ref, [candidate("Get Lucky", "Daft Punk", 248)]) is not None


def test_official_song_tolerates_a_slightly_different_length():
    assert select_best(track(), [candidate("Instant Crush", "Daft Punk", 350)]) is not None
    assert select_best(track(), [candidate("Daft Punk - Instant Crush", "Repost", 350, is_song=False)]) is None


def _fake_searches(monkeypatch, ytmusic, ytdlp):
    calls = []

    def search_ytdlp(query, cookies_file):
        calls.append(query)
        return list(ytdlp)

    monkeypatch.setattr(resolver, "_search_ytmusic_sync", lambda queries: list(ytmusic))
    monkeypatch.setattr(resolver, "_search_ytdlp_sync", search_ytdlp)
    return calls


async def _first_video_ids(ref, limit):
    video_ids = []
    async for video_id, _ in resolver.iter_youtube_candidates(ref):
        video_ids.append(video_id)
        if len(video_ids) == limit:
            break
    return video_ids


def test_sources_are_offered_best_first_then_from_the_fallback(monkeypatch):
    """Quand l'audio d'un candidat s'avère faux, l'appelant passe au suivant ;
    la recherche yt-dlp n'est lancée qu'une fois YouTube Music épuisé."""
    calls = _fake_searches(
        monkeypatch,
        ytmusic=[
            candidate("Daft Punk - Instant Crush (Lyrics)", "Fan", 336, is_song=False, video_id="paroles"),
            candidate("Instant Crush", "Daft Punk", 337, video_id="officiel"),
            candidate("Instant Crush (Instrumental)", "Daft Punk", 337, video_id="instru"),
        ],
        ytdlp=[candidate("Daft Punk - Instant Crush", "Uploader", 337, is_song=False, video_id="repost")],
    )
    assert asyncio.run(_first_video_ids(track(), limit=1)) == ["officiel"]
    assert calls == []
    assert asyncio.run(_first_video_ids(track(), limit=10)) == ["officiel", "paroles", "repost"]


def test_no_answer_from_either_engine_is_a_search_failure(monkeypatch):
    _fake_searches(monkeypatch, ytmusic=[], ytdlp=[])
    with pytest.raises(resolver.ResolutionError):
        asyncio.run(_first_video_ids(track(), limit=1))


def test_youtube_track_is_its_own_source(monkeypatch):
    calls = _fake_searches(monkeypatch, ytmusic=[], ytdlp=[])
    ref = TrackInfo(
        source="youtube", source_id="abc", title="Titre", artist="Chaîne", album=None, year=None,
        duration_seconds=None, cover_url=None,
    )
    assert asyncio.run(_first_video_ids(ref, limit=5)) == ["abc"]
    assert calls == []


def test_closest_duration_wins_a_tie():
    best = select_best(
        pnl("Zoulou tchaing", 325),
        [
            candidate("PNL - Zoulou Tchaing (Clip Vidéo)", "SayainProd", 328, is_song=False, video_id="clip"),
            candidate("PNL - Zoulou Tchaing", "Kenzi", 324, is_song=False, video_id="repost"),
        ],
    )
    assert best.video_id == "repost"
