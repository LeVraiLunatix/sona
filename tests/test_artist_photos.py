"""Stats : chaque artiste classé a sa propre photo et sa propre fiche, même
quand l'identifiant enregistré avec l'écoute est celui d'un autre artiste."""

from __future__ import annotations

import asyncio

from app.providers.base import ArtistInfo
from app.services import artist_photos
from app.services.stats import RankedItem

IDENTIFY = artist_photos._identify


class FakeDeezer:
    def __init__(self):
        self.artists = {
            "fave": ArtistInfo("deezer", "fave", "Favé", "https://photo/fave"),
            "mano": ArtistInfo("deezer", "mano", "La Mano 1.9", "https://photo/mano", fans=900_000),
            "mano-small": ArtistInfo("deezer", "mano-small", "La Mano 1.9", "https://photo/other", fans=12),
            "ninho": ArtistInfo("deezer", "ninho", "Ninho", "https://photo/ninho"),
        }
        self.searches = 0

    async def get_artist(self, artist_id):
        return self.artists[artist_id]

    async def search_artists(self, query, limit=10):
        self.searches += 1
        return [a for a in self.artists.values() if a.name.casefold() == query.casefold()] + [self.artists["fave"]]


class Deps:
    def __init__(self):
        self.deezer = FakeDeezer()


def item(name, source, source_id):
    return RankedItem(name, None, 6, 21, "https://cover", source, source_id)


def test_wrong_or_missing_artist_ids_are_fixed(monkeypatch):
    monkeypatch.setattr(artist_photos, "_identify", IDENTIFY)
    deps = Deps()
    wrong = item("La Mano 1.9", "deezer", "fave")      # identifiant d'un autre artiste
    right = item("Ninho", "deezer", "ninho")            # déjà bon : gardé, sans recherche
    apple = item("Favé", "apple", "123456")             # autre source : retrouvé sur Deezer
    asyncio.run(artist_photos.fix(deps, [wrong, right, apple]))

    assert (wrong.source_id, wrong.picture_url) == ("mano", "https://photo/mano")  # le plus suivi
    assert (right.source_id, right.picture_url) == ("ninho", "https://photo/ninho")
    assert (apple.source, apple.source_id, apple.picture_url) == ("deezer", "fave", "https://photo/fave")
    searches = deps.deezer.searches

    # Mis en cache : pas de nouvelle recherche au prochain affichage.
    again = item("La Mano 1.9", "deezer", "fave")
    asyncio.run(artist_photos.fix(deps, [again]))
    assert again.source_id == "mano" and deps.deezer.searches == searches
