from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_token
from app.api.schemas import RadioGroup, RadioStation, Track
from app.api.state import ApiDeps
from app.providers.deezer import DeezerError

router = APIRouter(tags=["browse"])

# Radios thématiques Deezer, triées à la main : `/radio/genres` mélange les
# vraies stations (« Rap français », « Années 80 ») à des dizaines de radios de
# test, de festivals passés ou de partenariats qui n'ont rien à faire dans
# l'app. Les identifiants de station Deezer sont stables.
CURATED_RADIOS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Rap & Hip-Hop", [
        ("39021", "Rap français"), ("30991", "Hip-hop"), ("31021", "Rap US"),
        ("37101", "Hip-Hop Old School"), ("40622", "Grime"),
    ]),
    ("Pop & Hits", [
        ("37151", "Hits"), ("31061", "Pop"), ("39604", "Français & Francophones"),
        ("38305", "Années 80"), ("30771", "Indie"), ("44784", "Energy Boost"),
    ]),
    ("R&B, Soul & Funk", [
        ("30881", "R&B"), ("30811", "R&B Old School"), ("38445", "Motown"),
        ("30861", "Soul"), ("30831", "Funk"), ("30841", "Disco"),
    ]),
    ("Électro & Dance", [
        ("36891", "Deep House"), ("648", "EDM"), ("30951", "Dance"),
        ("30851", "Techno"), ("30621", "Electronic"), ("37635", "Electro Swing"),
    ]),
    ("Rock & Metal", [
        ("42182", "Rock"), ("37765", "Classiques du rock"), ("30931", "Pop Rock"),
        ("37031", "Hard Rock"), ("30781", "Alternative"), ("30901", "Metal"),
    ]),
    ("Humeurs", [
        ("38435", "Pause acoustique"), ("39051", "Mélancolie"), ("39031", "Au coin du feu"),
        ("38225", "Concentration"), ("42924", "Humeurs intérieures"), ("45104", "Roadtrip"),
    ]),
    ("Chanson française", [
        ("38405", "Nouvelle scène"), ("38395", "Chanson française"), ("42522", "Variété française"),
    ]),
    ("Monde", [
        ("30941", "Reggaeton"), ("36791", "Latino"), ("31091", "Reggae"),
        ("39101", "Bossa Nova"), ("87", "World"),
    ]),
    ("Jazz & Classique", [
        ("31031", "Jazz"), ("31051", "Jazz vocal"), ("30661", "Classique"), ("30701", "Musiques de films"),
    ]),
]


def _picture(radio_id: str) -> str:
    # Redirige vers l'image 1000 px du CDN Deezer : pas d'appel réseau
    # nécessaire ici pour construire la liste.
    return f"https://api.deezer.com/radio/{radio_id}/image?size=xl"


@router.get("/browse/radios", response_model=list[RadioGroup])
async def list_radios(deps: ApiDeps = Depends(require_token)) -> list[RadioGroup]:
    return [
        RadioGroup(
            title=title,
            radios=[RadioStation(id=rid, title=name, picture_url=_picture(rid)) for rid, name in radios],
        )
        for title, radios in CURATED_RADIOS
    ]


@router.get("/radios/{radio_id}/tracks", response_model=list[Track])
async def radio_tracks(radio_id: str, deps: ApiDeps = Depends(require_token)) -> list[Track]:
    """Nouveau tirage à chaque appel : l'app en redemande quand la file se
    vide, la station ne s'arrête jamais."""
    if not radio_id.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Identifiant de radio invalide.")
    try:
        tracks = await deps.deezer.get_radio_tracks(radio_id)
    except DeezerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [Track.from_info(t) for t in tracks]
