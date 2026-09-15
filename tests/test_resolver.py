from app.providers.base import TrackInfo
from app.services.resolver import (
    Candidate,
    _query_variants,
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
