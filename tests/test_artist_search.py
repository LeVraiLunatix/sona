"""« Rechercher chez cet artiste ».

En septembre 2026, Deezer ne répond plus à sa syntaxe avancée : la requête
`artist:"PNL" Au DD` renvoyait zéro résultat, et `artist:"The Weeknd"` des
morceaux d'autres artistes. La recherche ciblée retombait donc sur iTunes.
"""

import asyncio

from app.providers import deezer as deezer_provider


def deezer_item(track_id, artist, title="Au DD"):
    return {
        "id": track_id,
        "title": title,
        "duration": 247,
        "artist": {"id": 1, "name": artist},
        "album": {"id": 2, "title": "Deux frères"},
    }


def search(monkeypatch, items, artist, query, index=0, limit=25):
    """Lance la recherche ciblée contre un Deezer simulé ; renvoie aussi les requêtes envoyées."""
    calls = []

    async def fake_get(self, path, params=None):
        calls.append((path, params))
        return {"data": items, "total": 999}

    monkeypatch.setattr(deezer_provider.DeezerClient, "_get", fake_get)
    client = deezer_provider.DeezerClient(client=object())
    tracks, total = asyncio.run(client.search_tracks_by_artist(artist, query, index=index, limit=limit))
    return tracks, total, calls


def test_a_plain_query_is_sent_and_only_that_artist_is_kept(monkeypatch):
    items = [
        deezer_item(1, "PNL"),
        deezer_item(2, "PNL SPAIN"),
        deezer_item(3, "Heuss L'enfoiré"),
        deezer_item(4, "PNL", title="Deux frères"),
    ]
    tracks, total, calls = search(monkeypatch, items, "PNL", "Au DD")

    assert [t.source_id for t in tracks] == ["1", "4"]
    # Le total de Deezer (999) ne vaut plus une fois le lot filtré.
    assert total == 2
    [(path, params)] = calls
    assert path == "/search/track"
    assert params["q"] == "PNL Au DD"
    assert params["limit"] == deezer_provider.ARTIST_SEARCH_POOL


def test_case_accents_and_punctuation_do_not_matter(monkeypatch):
    items = [deezer_item(1, "Céline Dion"), deezer_item(2, "AC/DC"), deezer_item(3, "celine dion")]
    tracks, _, _ = search(monkeypatch, items, "Celine Dion", "pour que tu m'aimes encore")
    assert [t.source_id for t in tracks] == ["1", "3"]

    tracks, _, _ = search(monkeypatch, items, "ACDC", "back in black")
    assert [t.source_id for t in tracks] == ["2"]


def test_pages_are_cut_inside_the_filtered_pool(monkeypatch):
    items = [deezer_item(i, "PNL" if i % 2 == 0 else "Autre") for i in range(24)]
    tracks, total, _ = search(monkeypatch, items, "PNL", "", index=10, limit=5)
    assert total == 12
    assert [t.source_id for t in tracks] == ["20", "22"]


def test_no_track_by_that_artist_gives_an_empty_page(monkeypatch):
    """Page vide : la recherche passe alors à iTunes, comme avant."""
    tracks, total, _ = search(monkeypatch, [deezer_item(1, "MC Solaar")], "PNL", "Hasta la vista")
    assert (tracks, total) == ([], 0)
