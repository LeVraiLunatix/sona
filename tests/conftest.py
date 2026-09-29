"""Réglages communs aux tests."""

import pytest

from app.api.routers import friends
from app.bot import lookup


@pytest.fixture(autouse=True)
def _empty_catalog_cache():
    """Chaque test repart d'un cache du catalogue vide : les faux
    fournisseurs d'un test ne doivent pas répondre dans le suivant."""
    lookup.clear_cache()
    friends._tastes.clear()
    yield
    lookup.clear_cache()
    friends._tastes.clear()
