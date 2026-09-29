"""Réglages communs aux tests."""

import pytest

from app.api.routers import friends, stats
from app.bot import lookup
from app.services import blindlive, concerts, party, tv_cast


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
    concerts.reset()
    yield
    lookup.clear_cache()
    friends._tastes.clear()
