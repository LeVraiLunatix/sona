import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import youtube_session

# Valeur factice : sert à vérifier qu'aucun log ne recopie un cookie.
COOKIE_VALUE = "valeur-secrete-du-cookie"
COOKIES = (
    "# Netscape HTTP Cookie File\n"
    f".youtube.com\tTRUE\t/\tTRUE\t1893456000\tLOGIN_INFO\t{COOKIE_VALUE}\n"
)
LOGGED_OUT_PAGE = b'<script>ytcfg.set({"INNERTUBE_API_KEY":"x","LOGGED_IN":false,"HL":"fr"});</script>'
LOGGED_IN_PAGE = b'<script>ytcfg.set({"LOGGED_IN": true});</script>'


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self, amt=None):
        return self._body if amt is None else self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_yt_dlp(seen, body=LOGGED_OUT_PAGE, error=None):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            seen["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            # Comme yt-dlp : le cookiefile est réécrit à la fermeture.
            Path(self.opts["cookiefile"]).write_text("# réécrit par yt-dlp\n")
            return False

        def urlopen(self, url):
            seen["url"] = url
            seen["copy"] = Path(self.opts["cookiefile"])
            seen["copy_content"] = seen["copy"].read_text()
            if error is not None:
                raise error
            return FakeResponse(body)

    return SimpleNamespace(YoutubeDL=FakeYoutubeDL)


@pytest.fixture
def cookies_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(COOKIES)
    return path


@pytest.fixture(autouse=True)
def reset_cooldown(monkeypatch):
    monkeypatch.setattr(youtube_session, "_last_check_at", None)


def test_parse_logged_in():
    assert youtube_session.parse_logged_in(LOGGED_OUT_PAGE.decode()) is False
    assert youtube_session.parse_logged_in(LOGGED_IN_PAGE.decode()) is True
    assert youtube_session.parse_logged_in("<html>consent.youtube.com</html>") is None


def test_probe_works_on_a_temporary_copy(monkeypatch, cookies_file):
    """yt-dlp réécrit son cookiefile en se fermant : la vérification ne doit
    jamais toucher au fichier qu'utilisent les téléchargements."""
    seen = {}
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp(seen))

    assert youtube_session.probe_logged_in(cookies_file) is False

    assert seen["url"] == "https://www.youtube.com/"
    assert seen["copy"] != cookies_file
    assert seen["copy_content"] == COOKIES
    assert not seen["copy"].exists()
    assert cookies_file.read_text() == COOKIES


def test_probe_keeps_tls_verification_and_a_short_timeout(monkeypatch, cookies_file):
    seen = {}
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp(seen))
    youtube_session.probe_logged_in(cookies_file)
    assert not seen["opts"].get("nocheckcertificate")
    assert seen["opts"]["socket_timeout"] <= 15


def test_probe_removes_the_copy_when_the_request_fails(monkeypatch, cookies_file):
    seen = {}
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp(seen, error=OSError("timed out")))
    with pytest.raises(OSError):
        youtube_session.probe_logged_in(cookies_file)
    assert not seen["copy"].exists()


def test_logged_out_session_logs_an_explicit_warning(monkeypatch, cookies_file, caplog):
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp({}))
    caplog.set_level(logging.INFO, logger=youtube_session.__name__)

    assert youtube_session.report_session(cookies_file, "démarrage") is False

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Cookies YouTube déconnectés" in warnings[0]
    assert "README" in warnings[0]
    assert COOKIE_VALUE not in caplog.text


def test_active_session_is_not_a_warning(monkeypatch, cookies_file, caplog):
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp({}, body=LOGGED_IN_PAGE))
    caplog.set_level(logging.INFO, logger=youtube_session.__name__)

    assert youtube_session.report_session(cookies_file, "démarrage") is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_check_failure_never_raises(monkeypatch, cookies_file, caplog):
    monkeypatch.setattr(youtube_session, "yt_dlp", _fake_yt_dlp({}, error=OSError("timed out")))
    caplog.set_level(logging.INFO, logger=youtube_session.__name__)

    assert youtube_session.report_session(cookies_file, "démarrage") is None
    assert "impossible" in caplog.text


def test_background_checks_are_rate_limited(monkeypatch, cookies_file):
    calls = []
    monkeypatch.setattr(youtube_session, "report_session", lambda path, reason: calls.append(reason))

    async def scenario():
        first = youtube_session.schedule_session_check(cookies_file, "démarrage")
        second = youtube_session.schedule_session_check(cookies_file, "mur anti-bot")
        assert second is None
        await first

    asyncio.run(scenario())
    assert calls == ["démarrage"]
