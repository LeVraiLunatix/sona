"""Stats d'écoute : périodes, agrégations dans le fuseau de l'utilisateur,
enregistrement des écoutes et import Last.fm (faux transport, sans réseau)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.repository import Play
from app.providers.lastfm import ImportStatus, LastfmClient, import_history
from app.services import stats

AUTH = {"Authorization": "Bearer test-token"}
PARIS = ZoneInfo("Europe/Paris")


def play(when: str, title="Titre", artist="Artiste", album=None, seconds=None) -> Play:
    return Play(played_at=when, title=title, artist=artist, album=album, listened_seconds=seconds)


def test_period_ranges_in_local_time():
    now = datetime(2026, 9, 30, 10, 0, tzinfo=PARIS)  # un mercredi
    week = stats.period_range("week", 0, now)
    assert week.start == datetime(2026, 9, 28, tzinfo=PARIS)
    assert week.end == datetime(2026, 10, 5, tzinfo=PARIS)
    assert week.label == "Cette semaine"

    month = stats.period_range("month", -9, now)
    assert (month.start.year, month.start.month, month.end.month) == (2025, 12, 1)
    assert month.label == "Décembre 2025"

    assert stats.period_range("year", -1, now).label == "2025"
    assert stats.period_range("all", 0, now).start is None


def test_report_counts_tops_and_local_days():
    now = datetime(2026, 9, 30, 12, 0, tzinfo=PARIS)
    rng = stats.period_range("week", 0, now)
    plays = [
        # 23 h 30 UTC le lundi = 1 h 30 le mardi à Paris.
        play("2026-09-28T23:30:00+00:00", "A", "Ziak", "Akimbo", 200),
        play("2026-09-29T10:00:00+00:00", "A", "Ziak", "Akimbo", 200),
        play("2026-09-29T11:00:00+00:00", "B", "Gazo", None, 100),
    ]
    first = {"ziak": "2025-01-01T00:00:00+00:00", "gazo": "2026-09-29T11:00:00+00:00"}
    report = stats.build_report(rng, 0, plays, 1, first, [p.played_at for p in plays], now)

    assert (report.plays, report.minutes, report.artists, report.tracks, report.albums) == (3, 8, 2, 2, 1)
    assert [a.name for a in report.top_artists] == ["Ziak", "Gazo"]
    assert report.top_tracks[0].name == "A" and report.top_tracks[0].plays == 2
    assert [b.plays for b in report.timeline] == [0, 3, 0, 0, 0, 0, 0]  # tout le mardi
    assert report.timeline[1].label == "Mar"
    assert report.hours[1] == 1 and report.hours[12] == 1 and report.hours[13] == 1
    assert [a.name for a in report.discoveries] == ["Gazo"]
    assert report.top_weekday == "mardi"
    assert report.previous_plays == 1


def test_streak_counts_consecutive_days_until_yesterday():
    today = datetime(2026, 9, 30, tzinfo=PARIS).date()
    stamps = ["2026-09-27T10:00:00+00:00", "2026-09-28T10:00:00+00:00", "2026-09-29T10:00:00+00:00"]
    assert stats.streak_days(stamps, PARIS, today) == 3
    assert stats.streak_days(["2026-09-20T10:00:00+00:00"], PARIS, today) == 0


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.app_state = main_module.app.state
        yield test_client


def test_plays_are_recorded_deduplicated_and_counted(client):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body = {"plays": [{
        "title": "Room", "artist": "Ziak", "album": "Chrome", "source": "deezer", "source_id": "1",
        "duration_seconds": 177, "listened_seconds": 150, "played_at": now.isoformat(),
    }]}
    assert client.post("/plays", headers=AUTH, json=body).json() == {"added": 1}
    assert client.post("/plays", headers=AUTH, json=body).json() == {"added": 0}

    recent = client.get("/plays/recent", headers=AUTH).json()
    assert [(p["title"], p["artist"], p["origin"]) for p in recent] == [("Room", "Ziak", "sona")]

    report = client.get("/stats", headers=AUTH, params={"period": "all", "tz": "Europe/Paris"}).json()
    assert report["plays"] == 1 and report["minutes"] == 2
    assert report["top_artists"][0]["name"] == "Ziak"
    assert report["streak_days"] == 1


def test_stats_rejects_unknown_period_and_import_needs_config(client):
    assert client.get("/stats", headers=AUTH, params={"period": "decade"}).status_code == 400
    assert client.get("/stats/import/lastfm", headers=AUTH).json()["configured"] is False
    assert client.post("/stats/import/lastfm", headers=AUTH).status_code == 503


class MemoryRepo:
    def __init__(self):
        self.plays: list[Play] = []

    async def plays_latest(self, user_id, origin):
        stamps = [p.played_at for p in self.plays if p.origin == origin]
        return max(stamps) if stamps else None

    async def plays_add(self, user_id, plays):
        known = {(p.played_at, p.title, p.artist) for p in self.plays}
        fresh = [p for p in plays if (p.played_at, p.title, p.artist) not in known]
        self.plays.extend(fresh)
        return fresh

    async def plays_timestamps(self, user_id, origin):
        return {p.played_at for p in self.plays if p.origin == origin}


def lastfm_page(page, total, tracks):
    return {"recenttracks": {"track": tracks, "@attr": {"page": str(page), "totalPages": str(total)}}}


def test_lastfm_import_pages_skips_now_playing_and_resumes(monkeypatch):
    monkeypatch.setattr("app.providers.lastfm.PAGE_DELAY", 0)
    requests = []

    def handler(request):
        requests.append(dict(request.url.params))
        page = int(request.url.params["page"])
        if page == 1:
            return httpx.Response(200, json=lastfm_page(1, 2, [
                {"name": "En cours", "artist": {"#text": "X"}, "@attr": {"nowplaying": "true"}},
                {"name": "Room", "artist": {"#text": "Ziak"}, "album": {"#text": "Chrome"},
                 "date": {"uts": "1767225600"},
                 "image": [{"#text": "https://img/2a96cbd8b46e442fc41c2b86b821562f.png"}]},
            ]))
        return httpx.Response(200, json=lastfm_page(2, 2, {
            "name": "La nuit", "artist": {"#text": "Ziak"}, "date": {"uts": "1767200000"},
        }))

    client = LastfmClient("key", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    repo, status = MemoryRepo(), ImportStatus()
    asyncio.run(import_history(client, repo, 1, "moi", status))

    assert status.imported == 2 and status.error is None and not status.running
    room = next(p for p in repo.plays if p.title == "Room")
    assert room.played_at == "2026-01-01T00:00:00+00:00" and room.cover_url is None and room.album == "Chrome"
    assert "from" not in requests[0]

    # Deuxième passage : ne demande que ce qui suit la dernière écoute connue.
    asyncio.run(import_history(client, repo, 1, "moi", ImportStatus()))
    assert requests[-1]["from"] == "1767225601"


def test_lastfm_error_is_reported():
    client = LastfmClient("key", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"error": 6, "message": "User not found"})
    )))
    status = ImportStatus()
    asyncio.run(import_history(client, MemoryRepo(), 1, "inconnu", status))
    assert status.error == "Last.fm : User not found" and not status.running


def test_recap_story_for_the_month(client):
    # Le récap porte sur le mois dernier : écoutes au milieu de ce mois-là.
    today = datetime.now(ZoneInfo("Europe/Paris"))
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=15, hour=12)
    now = last_month.astimezone(timezone.utc).replace(microsecond=0)
    plays = [
        {"title": "Room", "artist": "Ziak", "source": "deezer", "source_id": "1", "duration_seconds": 180,
         "played_at": (now - timedelta(minutes=2 * i)).isoformat()}
        for i in range(12)
    ] + [{"title": "Autre", "artist": "Gazo", "duration_seconds": 200,
          "played_at": (now - timedelta(minutes=30)).isoformat()}]
    client.post("/plays", headers=AUTH, json={"plays": plays})

    # Mois en cours : pas encore de récap.
    early = client.get("/stats/recap", headers=AUTH, params={"tz": "Europe/Paris"})
    assert early.status_code == 409 and "1er" in early.json()["detail"]

    recap = client.get("/stats/recap", headers=AUTH, params={"tz": "Europe/Paris", "offset": -1}).json()
    assert recap["period"] == "month" and recap["plays"] == 13
    assert recap["top_artists"][0]["name"] == "Ziak"
    assert recap["favourite_track"]["title"] == "Room" and recap["favourite_track"]["source_id"] == "1"
    assert recap["first_track"]["title"] in ("Room", "Autre")
    assert recap["personality"]["title"] == "Le fan absolu"
    assert recap["biggest_day"]["minutes"] >= 36
    assert client.get("/stats/recap", headers=AUTH, params={"period": "day", "offset": -1}).status_code == 400
    assert "lundi" in client.get("/stats/recap", headers=AUTH, params={"period": "week"}).json()["detail"]
