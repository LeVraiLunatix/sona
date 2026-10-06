"""Page publique « J'écoute » et titre du jour."""

from app.providers.base import TrackInfo
from app.services import mixes as mixes_service
from app.services.mixes import Mix
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def test_public_link_lifecycle(client):
    me = login(client, "alice")
    assert client.get("/me/public-link", headers=me).json() == {"token": None}
    token = client.post("/me/public-link", headers=me).json()["token"]
    assert client.get("/me/public-link", headers=me).json() == {"token": token}

    # Sans compte : la page et ce qu'elle affiche.
    page = client.get(f"/p/{token}")
    assert page.status_code == 200 and "J'écoute" in page.text
    assert page.headers["x-robots-tag"] == "noindex"
    empty = client.get(f"/p/{token}/now").json()
    assert empty["playing"] is None and empty["last"] is None and empty["name"]

    client.post("/plays/now", headers=me, json={"title": "Onizuka", "artist": "PNL", "duration_seconds": 200, "position_seconds": 30})
    playing = client.get(f"/p/{token}/now").json()["playing"]
    assert playing["title"] == "Onizuka" and playing["artist"] == "PNL" and playing["duration"] == 200
    assert 29 <= playing["position"] <= 40

    # Écoute en privé : plus rien d'affiché.
    client.put("/auth/me", headers=me, json={"share_listening": False})
    assert client.get(f"/p/{token}/now").json()["playing"] is None

    # Nouveau lien : l'ancien ne marche plus ; supprimé : plus rien.
    other = client.post("/me/public-link", headers=me).json()["token"]
    assert other != token
    assert client.get(f"/p/{token}/now").status_code == 404
    assert client.delete("/me/public-link", headers=me).status_code == 204
    assert client.get(f"/p/{other}").status_code == 404
    assert client.get("/p/x/now").status_code == 404


def test_public_link_needs_account(client):
    assert client.post("/me/public-link").status_code in (401, 403)


def _track(i):
    return TrackInfo(source="deezer", source_id=str(i), title=f"Titre {i}", artist="Artiste", album=None, year=None,
                     duration_seconds=180, cover_url=None)


def test_daily_track(client, monkeypatch):
    me = login(client, "alice")
    mixes = [Mix(id="daily", title="Mix du jour", subtitle="", tracks=[_track(1), _track(2)]),
             Mix(id="discoveries", title="Découvertes", subtitle="", tracks=[_track(i) for i in range(10, 20)])]

    async def fake(deps, user_id, refresh=False):
        return mixes

    monkeypatch.setattr(mixes_service, "get_mixes", fake)
    first = client.get("/home/daily", headers=me).json()
    assert first["track"]["source_id"] in {str(i) for i in range(10, 20)}
    assert "jamais écouté" in first["reason"]
    # Le même toute la journée.
    assert client.get("/home/daily", headers=me).json() == first

    mixes[1].tracks = []
    assert client.get("/home/daily", headers=me).json()["track"]["source_id"] in {"1", "2"}
    mixes.clear()
    assert client.get("/home/daily", headers=me).json()["track"] is None
