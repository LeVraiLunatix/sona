import logging

from app.logging_config import YtDlpLogger

COOKIE_WARNING = (
    "[youtube] abc: The provided YouTube account cookies are no longer valid. "
    "They have likely been rotated in the browser as a security measure."
)


def _ytdlp_logger(caplog, clock=lambda: 0.0):
    caplog.set_level(logging.DEBUG, logger="test.ytdlp")
    return YtDlpLogger(logging.getLogger("test.ytdlp"), clock=clock)


def _records(caplog):
    return [(r.levelno, r.getMessage()) for r in caplog.records]


def test_cookie_warnings_reach_the_logs(caplog):
    """Avec `no_warnings`, cet avertissement disparaissait : une session
    Google morte ne laissait aucune trace dans les logs."""
    _ytdlp_logger(caplog).warning(COOKIE_WARNING)
    assert _records(caplog) == [(logging.WARNING, COOKIE_WARNING)]


def test_javascript_runtime_warnings_reach_the_logs(caplog):
    _ytdlp_logger(caplog).warning("[youtube] abc: No supported JavaScript runtime could be found.")
    assert caplog.records[0].levelno == logging.WARNING


def test_routine_warnings_stay_in_debug(caplog):
    _ytdlp_logger(caplog).warning("[youtube] abc: Some web client https formats have been skipped")
    assert caplog.records[0].levelno == logging.DEBUG


def test_repeated_warning_is_logged_once_per_window(caplog):
    """yt-dlp répète l'avertissement de cookies après chaque requête d'une
    même extraction : une ligne suffit."""
    now = [1000.0]
    ytdlp = _ytdlp_logger(caplog, clock=lambda: now[0])
    ytdlp.warning(COOKIE_WARNING)
    ytdlp.warning(COOKIE_WARNING)
    now[0] += 61
    ytdlp.warning(COOKIE_WARNING)
    assert [level for level, _ in _records(caplog)] == [logging.WARNING, logging.WARNING]


def test_errors_stay_visible_without_terminal_colours(caplog):
    _ytdlp_logger(caplog).error("\x1b[0;31mERROR:\x1b[0m [youtube] abc: Sign in to confirm you're not a bot")
    assert _records(caplog) == [
        (logging.ERROR, "ERROR: [youtube] abc: Sign in to confirm you're not a bot"),
    ]


def test_pm2_node_ipc_variables_are_removed_before_running_deno(monkeypatch):
    import os

    from app.services.ytdlp_runtime import with_js_runtimes

    monkeypatch.setenv("NODE_CHANNEL_FD", "3")
    monkeypatch.setenv("NODE_CHANNEL_SERIALIZATION_MODE", "json")
    opts = with_js_runtimes({})
    assert "NODE_CHANNEL_FD" not in os.environ
    assert "NODE_CHANNEL_SERIALIZATION_MODE" not in os.environ
    assert opts["js_runtimes"]
