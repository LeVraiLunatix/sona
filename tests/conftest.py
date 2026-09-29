"""Réglages communs aux tests."""

import pytest

from app.api.routers import friends, stats
from app.bot import lookup
from app.services import artist_photos, blindlive, concerts, connect, instrumental, party, stream_health, tv_cast


@pytest.fixture(autouse=True)
def _no_artist_photo_lookup(monkeypatch):
    """Les stats ne vont pas chercher les photos d'artistes sur le vrai
    Deezer pendant les tests (test_artist_photos le fait avec un faux)."""
    artist_photos.reset()

    async def unknown(deps, name, source, source_id):
        return None

    monkeypatch.setattr(artist_photos, "_identify", unknown)


@pytest.fixture(autouse=True)
def _empty_catalog_cache():
    """Chaque test repart d'un cache du catalogue vide : les faux
    fournisseurs d'un test ne doivent pas répondre dans le suivant."""
    lookup.clear_cache()
    friends._tastes.clear()
    stats._lastfm_sync.clear()
    party.reset()
    blindlive.reset()
    tv_cast.reset()
    instrumental.reset()
    concerts.reset()
    connect.reset()
    stream_health.reset()
    yield
    lookup.clear_cache()
    friends._tastes.clear()
