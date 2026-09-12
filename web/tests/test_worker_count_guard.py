"""The single-worker warning has to see how the server was actually launched.

`WEB_CONCURRENCY` alone was not enough: a production deployment set the count
with gunicorn's `--workers 2` on the command line and ran two workers for a week
with the warning never firing, because the variable was absent and the check
read its own default. These tests pin the spellings that must be caught, the
ones that must not be mistaken for a count, and the cases where the honest
answer is "unknown" rather than a number.

The expectations here follow gunicorn's own parser (`gunicorn/config.py`), not a
convenient approximation: `type=int` on the option, the last occurrence winning,
`shlex` splitting of `GUNICORN_CMD_ARGS`, and `--` ending the options.
"""

from __future__ import annotations

import logging

import pytest

import web.api.app as app_module
from web.api.app import (
    _configured_worker_count,
    _worker_count_from_argv,
)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--workers", "2"], "2"),
        (["--workers=4"], "4"),
        (["-w", "3"], "3"),
        (["-w2"], "2"),
        # The drifted regression vector: 0.0.0.0, 2 workers, 2 threads.
        (
            [
                "--bind",
                "0.0.0.0:5001",
                "--workers",
                "2",
                "--threads",
                "2",
                "--preload",
                "web.api.app:create_app()",
            ],
            "2",
        ),
        (["--workers", "1"], "1"),
        # gunicorn parses the value with int(), so these are 2, 1 and 10.
        (["--workers", "+2"], "2"),
        (["--workers", "01"], "1"),
        (["--workers", "1_0"], "10"),
        # A repeated option stores the last one, both ways round.
        (["--workers", "1", "--workers", "2"], "2"),
        (["--workers", "2", "-w", "1"], "1"),
        # Named by nothing: absence, not a default.
        ([], None),
        (["--threads", "8", "web.api.app:create_app()"], None),
        # Nothing after `--` is an option.
        (["--", "--workers", "2"], None),
        # Flags that merely start the same way are not this one.
        (["--worker-class", "gthread", "--worker-connections", "2"], None),
        # A trailing flag with no value must not read past the end.
        (["--workers"], None),
        # Values gunicorn's int() would refuse; it would not start at all.
        (["--workers", "auto"], None),
        (["--workers", ""], None),
    ],
)
def test_the_argument_list_is_read_the_way_gunicorn_reads_it(
    argv: list[str], expected: str | None
) -> None:
    assert _worker_count_from_argv(argv) == expected


def test_the_command_line_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The precedence gunicorn itself uses — and the case that went unnoticed."""
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", "1")
    monkeypatch.setattr("sys.argv", ["/usr/bin/gunicorn", "--workers", "2"])
    count, source = _configured_worker_count()
    assert count == "2"
    assert "the command line" in source


def test_gunicorn_cmd_args_is_read_when_the_command_line_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", "--workers=3 --threads 2")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn", "web.api.app:create_app()"])
    count, source = _configured_worker_count()
    assert count == "3"
    assert "GUNICORN_CMD_ARGS" in source


def test_gunicorn_cmd_args_is_split_the_way_gunicorn_splits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gunicorn uses `shlex.split`, so a quoted value is still a number. Plain
    `str.split` would read `"2"` with its quotes and report nothing."""
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", '--workers "2"')
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    assert _configured_worker_count()[0] == "2"


def test_unbalanced_quoting_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", '--workers "2')
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    assert _configured_worker_count() == ("unknown", "GUNICORN_CMD_ARGS cannot be parsed")


def test_a_non_gunicorn_launch_ignores_gunicorn_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python web/api/app.py --workers 2` runs Flask's development server,
    which ignores the flag. Warning about it would be a false alarm."""
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", "--workers=4")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["web/api/app.py", "--workers", "2"])
    assert _configured_worker_count() == ("1", "not a gunicorn launch")


def test_web_concurrency_still_answers_when_nothing_else_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", "4")
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    assert _configured_worker_count() == ("4", "WEB_CONCURRENCY sets 4 workers")


def test_web_concurrency_is_compared_as_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WEB_CONCURRENCY=01` is one worker, and must not warn."""
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", "01")
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    assert _configured_worker_count()[0] == "1"


def test_a_single_worker_launch_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn", "--workers", "1", "--threads", "8"])
    assert _configured_worker_count()[0] == "1"


def _warnings_from_a_launch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, argv: list[str]
) -> list[str]:
    from web.api.app import create_app

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    with caplog.at_level(logging.WARNING):
        create_app(testing=True)
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_a_multi_worker_launch_warns_at_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The end the guard exists for: the warning reaches the log, naming where
    the count came from. Without this, the parsing above could be perfect and
    `create_app` could still never call it."""
    warnings = _warnings_from_a_launch(
        monkeypatch, caplog, ["gunicorn", "--workers", "2", "--threads", "2"]
    )
    single_worker = [m for m in warnings if "single-worker" in m]
    assert single_worker, f"no single-worker warning in {warnings}"
    assert "the command line sets 2 workers" in single_worker[0]
    # The consequences an operator needs to weigh, not just "don't do that".
    assert "rate limiting" in single_worker[0]


def test_a_single_worker_launch_warns_about_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The other half of the call site: the correct launch line stays silent."""
    warnings = _warnings_from_a_launch(
        monkeypatch, caplog, ["gunicorn", "--workers", "1", "--threads", "8"]
    )
    assert not [m for m in warnings if "single-worker" in m], warnings


def test_an_unreadable_launch_says_so_at_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A gunicorn launch without any worker declaration must produce the
    "cannot verify" warning, not silence — silence is what a fabricated "1"
    would buy."""
    warnings = _warnings_from_a_launch(monkeypatch, caplog, ["gunicorn"])
    cannot_verify = [m for m in warnings if "Cannot verify" in m]
    assert cannot_verify, f"no cannot-verify warning in {warnings}"
    assert "names no worker count" in cannot_verify[0]


def test_python_m_gunicorn_is_recognized_via_server_software(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["__main__.py", "--workers", "2"])
    count, source = _configured_worker_count()
    assert count == "2"
    assert "the command line sets 2 workers" in source


def test_dev_server_ignores_web_concurrency_when_not_gunicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", "4")
    monkeypatch.setattr("sys.argv", ["web/api/app.py"])
    assert _configured_worker_count() == ("1", "not a gunicorn launch")


def test_sfda_config_workers_declares_config_file_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", "1")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    assert _configured_worker_count() == ("1", "gunicorn.conf.py sets 1 workers")


def test_command_line_overrides_sfda_config_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", "4")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn", "--workers", "1"])
    count, source = _configured_worker_count()
    assert count == "1"
    assert "the command line sets 1 workers" in source


def test_guard_never_calls_getcwd(monkeypatch: pytest.MonkeyPatch) -> None:
    def _exploding_getcwd() -> str:
        raise AssertionError("os.getcwd() was called by the guard")

    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", "1")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    with monkeypatch.context() as m:
        m.setattr("os.getcwd", _exploding_getcwd)
        count, _ = _configured_worker_count()
    assert count == "1"


def test_post_step_0_production_line_boots_silently(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "GUNICORN_CMD_ARGS", None)
    monkeypatch.setitem(app_module._LAUNCH_ENV, "SFDA_CONFIG_WORKERS", "1")
    monkeypatch.setitem(app_module._LAUNCH_ENV, "WEB_CONCURRENCY", None)
    prod_argv = [
        "/var/www/sfda-copilot/venv/bin/gunicorn",
        "--bind",
        "127.0.0.1:5001",
        "--threads",
        "8",
        "--preload",
        "--max-requests",
        "1000",
        "--max-requests-jitter",
        "100",
        "--chdir",
        "/var/www/sfda-copilot",
        "web.api.app:create_app()",
    ]
    from web.api.app import create_app

    monkeypatch.setattr("sys.argv", prod_argv)
    with caplog.at_level(logging.WARNING):
        create_app(testing=True)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not [m for m in warnings if "single-worker" in m], warnings
