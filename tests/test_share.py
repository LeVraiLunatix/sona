"""Liens de partage : création, réutilisation, expiration, révocation, page
publique (Open Graph, échappement), extraits de 30 s et limite de visites —
catalogue et Telegram remplacés par des faux, aucun appel réseau."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers import share as share_router
from app.bot import lookup
from app.providers.base import AlbumInfo, TrackInfo
from app.services import share

AUTH = {"Authorization": "Bearer test-token"}

TRACK = TrackInfo("deezer", "3135556", "Harder <Better> \"Faster\"", "Daft Punk", "Discovery", "2001", 224,
                  "https://e-cdns-images.dzcdn.net/images/cover/abc/250x250-000000-80-0-0.jpg",
                  preview_url="https://cdnt-preview.dzcdn.net/api/1/1/a/b/c/preview.mp3")
ALBUM = AlbumInfo("deezer", "302127", "Discovery", "Daft Punk", "27", "2001",
                  "https://e-cdns-images.dzcdn.net/images/cover/abc/250x250-000000-80-0-0.jpg", 2, 500,
                  tracks=[TRACK, TrackInfo("deezer", "3135553", "One More Time", "Daft Punk", "Discovery", "2001", 320, None)])


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("SHARE_BASE_URL", "https://sona.exemple.fr/")
    monkeypatch.setenv("SONA_WEB_URL", "https://web.exemple.fr")

    async def get_track(deps, source, source_id):
        if source_id == TRACK.source_id:
            return TRACK
        if source_id == "3135553":
            return TrackInfo("deezer", "3135553", "One More Time", "Daft Punk", None, None, 320, None,
                             preview_url="https://cdnt-preview.dzcdn.net/one.mp3")
        raise lookup.UnknownSourceError(source)

    async def get_album(deps, source, source_id):
        return ALBUM

    monkeypatch.setattr(lookup, "get_track", get_track)
    monkeypatch.setattr(lookup, "get_album", get_album)

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.app_state = main_module.app.state
        yield test_client


def create(client, **payload):
    return client.post("/me/shares", headers=AUTH, json={"source": "deezer", **payload})


def test_track_link_and_public_page(client):
    made = create(client, kind="track", id="3135556")
    assert made.status_code == 201, made.text
    body = made.json()
    token = body["token"]
    assert len(token) >= 20 and body["url"] == f"https://sona.exemple.fr/s/{token}"
    assert (body["title"], body["subtitle"], body["active"], body["expires_at"]) == (TRACK.title, "Daft Punk", True, None)
    # Même contenu, sans expiration : le même lien.
    assert create(client, kind="track", id="3135556").json()["token"] == token

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    html = page.text
    # Aperçu riche pour les messageries, titre échappé partout.
    assert '<meta property="og:title" content="Harder &lt;Better&gt; &quot;Faster&quot;">' in html
    assert '<meta property="og:type" content="music.song">' in html
    assert 'property="og:image" content="https://e-cdns-images.dzcdn.net/images/cover/abc/1000x1000-000000-80-0-0.jpg"' in html
    assert "<Better>" not in html
    # Jamais d'audio complet : pas de /stream, et l'extrait passe par Deezer.
    assert "/stream/" not in html and "preview.mp3" not in html
    assert f'href="https://web.exemple.fr/#/s/{token}"' in html
    assert "https://www.deezer.com/track/3135556" in html
    assert page.headers["x-robots-tag"].startswith("noindex")
    assert "default-src 'none'" in page.headers["content-security-policy"]

    preview = client.get(f"/s/{token}/preview/0", follow_redirects=False)
    assert preview.status_code == 302 and preview.headers["location"] == TRACK.preview_url
    assert client.get(f"/s/{token}/preview/5", follow_redirects=False).status_code == 404

    listed = client.get("/me/shares", headers=AUTH).json()
    assert [(s["token"], s["views"]) for s in listed] == [(token, 1)]


def test_album_page_lists_tracks_with_previews(client):
    token = create(client, kind="album", id="302127").json()["token"]
    html = client.get(f"/s/{token}").text
    assert html.count('<li data-i=') == 2 and "One More Time" in html and "5:20" in html
    assert "https://www.deezer.com/album/302127" in html
    preview = client.get(f"/s/{token}/preview/1", follow_redirects=False)
    assert preview.headers["location"] == "https://cdnt-preview.dzcdn.net/one.mp3"


def test_expiry_and_revocation(client):
    expiring = create(client, kind="track", id="3135556", expires_in_hours=24).json()
    permanent = create(client, kind="track", id="3135556").json()
    assert expiring["token"] != permanent["token"] and expiring["expires_at"]

    # Expiré : la page le dit (410), et plus d'extrait.
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db = client.app_state.deps.repo._db

    async def expire():
        await db.conn.execute("UPDATE share_links SET expires_at=? WHERE token=?", (past, expiring["token"]))
        await db.conn.commit()

    client.portal.call(expire)
    gone = client.get(f"/s/{expiring['token']}")
    assert gone.status_code == 410 and "expiré" in gone.text
    assert client.get(f"/s/{expiring['token']}/preview/0", follow_redirects=False).status_code == 404

    assert client.delete(f"/me/shares/{permanent['token']}", headers=AUTH).status_code == 204
    revoked = client.get(f"/s/{permanent['token']}")
    assert revoked.status_code == 410 and "existe plus" in revoked.text
    assert client.delete(f"/me/shares/{permanent['token']}", headers=AUTH).status_code == 404
    assert client.get("/s/inconnu-mais-assez-long").status_code == 404


def test_members_open_a_link_in_sona(client):
    token = create(client, kind="album", id="302127").json()["token"]
    assert client.get(f"/shares/{token}").status_code == 401
    opened = client.get(f"/shares/{token}", headers=AUTH).json()
    assert (opened["kind"], opened["source"], opened["id"]) == ("album", "deezer", "302127")
    assert [t["title"] for t in opened["tracks"]] == [TRACK.title, "One More Time"]


def test_playlist_share_needs_access(client):
    pid = client.post("/me/playlists", headers=AUTH, json={"name": "Soirée", "tracks": [
        {"source": "deezer", "source_id": "3135556", "title": "Harder", "artist": "Daft Punk", "cover_url": "https://img/1.jpg"},
    ]}).json()["id"]
    made = create(client, kind="playlist", id=str(pid)).json()
    assert (made["source"], made["title"], made["subtitle"]) == ("sona", "Soirée", "1 titre")
    html = client.get(f"/s/{made['token']}").text
    assert '<meta property="og:type" content="music.playlist">' in html and "Harder" in html

    async def someone_elses():
        return await client.app_state.deps.repo.playlist_create(99, "Privée d'un autre")

    other = client.portal.call(someone_elses)
    assert create(client, kind="playlist", id=str(other)).status_code == 400
    assert create(client, kind="artist", id="1").status_code == 400
    assert create(client, kind="track", id="introuvable").status_code == 400


def test_public_pages_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(share_router, "RATE_LIMIT", 3)
    token = create(client, kind="track", id="3135556").json()["token"]
    codes = [client.get(f"/s/{token}", headers={"X-Forwarded-For": "203.0.113.9"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # Un autre visiteur n'est pas puni pour le premier.
    assert client.get(f"/s/{token}", headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200


def test_telegram_button_uses_the_bot_name(client, monkeypatch):
    async def bot_username(settings):
        return "SonaBot"

    monkeypatch.setattr(share, "bot_username", bot_username)
    token = create(client, kind="track", id="3135556").json()["token"]
    assert f"https://t.me/SonaBot?start=s_{token}" in client.get(f"/s/{token}").text
