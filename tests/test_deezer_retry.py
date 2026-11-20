"""Deezer : nouvel essai sur les échecs passagers (quota, panne) et limiteur de débit — sans réseau."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.providers import deezer as deezer_module
from app.providers.deezer import DeezerClient, DeezerError

QUOTA = {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}


def client_with(handler) -> DeezerClient:
    return DeezerClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(deezer_module, "RETRY_DELAYS", (0.0, 0.0))


def run(coro):
    return asyncio.run(coro)


def test_quota_error_is_retried_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=QUOTA if len(calls) < 3 else {"data": [], "total": 0})

    found, total = run(client_with(handler).search_tracks("music sounds"))
    assert (found, total) == ([], 0)
    assert len(calls) == 3


def test_server_errors_and_timeouts_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        if len(calls) == 2:
            raise httpx.ReadTimeout("trop lent", request=request)
        return httpx.Response(200, json={"data": [], "total": 0})

    assert run(client_with(handler).search_tracks("x")) == ([], 0)
    assert len(calls) == 3


def test_gives_up_after_the_last_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=QUOTA)

    with pytest.raises(DeezerError, match="Quota"):
        run(client_with(handler).search_tracks("x"))
    assert len(calls) == 3  # un essai + deux nouveaux


def test_real_answers_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"error": {"type": "DataException", "message": "no data", "code": 800}})

    with pytest.raises(DeezerError, match="no data"):
        run(client_with(handler).get_artist("1"))
    assert len(calls) == 1


def test_requests_are_spread_to_stay_under_deezer_quota(monkeypatch):
    monkeypatch.setattr(deezer_module, "RATE_MAX", 3)
    monkeypatch.setattr(deezer_module, "RATE_WINDOW", 0.3)
    client = client_with(lambda request: httpx.Response(200, json={"data": [], "total": 0}))

    async def burst():
        await asyncio.gather(*(client.search_tracks("x") for _ in range(7)))

    started = time.monotonic()
    run(burst())
    # 7 requêtes à 3 par 0,3 s : au moins deux fenêtres complètes d'attente.
    assert time.monotonic() - started >= 0.55
