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

from web.api.app import (
    _configured_worker_count,
    _gunicorn_config_file_in_play,
    _worker_count_from_argv,
)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--workers", "2"], "2"),
        (["--workers=4"], "4"),
        (["-w", "3"], "3"),
        (["-w2"], "2"),
        # The real production line, verbatim apart from the paths.
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


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["-c", "gunicorn.conf.py"], True),
        (["--config", "gunicorn.conf.py"], True),
        (["--config=gunicorn.conf.py"], True),
        (["-cgunicorn.conf.py"], True),
        ([], False),
        (["--threads", "8"], False),
        (["--", "-c", "gunicorn.conf.py"], False),
    ],
)
def test_a_config_file_is_noticed_however_it_is_named(
    argv: list[str], expected: bool, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The default-discovery half is covered separately below; this pins the
    flag spellings, from a directory with no `gunicorn.conf.py` in it."""
    monkeypatch.chdir(tmp_path)
    assert _gunicorn_config_file_in_play(argv) is expected


def test_a_discovered_config_file_counts_even_with_no_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """gunicorn loads ./gunicorn.conf.py without being asked, so the absence of
    `-c` proves nothing."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gunicorn.conf.py").write_text("workers = 2\n", encoding="utf-8")
    assert _gunicorn_config_file_in_play([]) is True


def test_the_command_line_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The precedence gunicorn itself uses — and the case that went unnoticed."""
    monkeypatch.setattr("sys.argv", ["/usr/bin/gunicorn", "--workers", "2"])
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    count, source = _configured_worker_count()
    assert count == "2"
    assert "command line" in source


def test_gunicorn_cmd_args_is_read_when_the_command_line_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["gunicorn", "web.api.app:create_app()"])
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--workers=3 --threads 2")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    count, source = _configured_worker_count()
    assert count == "3"
    assert "GUNICORN_CMD_ARGS" in source


def test_gunicorn_cmd_args_is_split_the_way_gunicorn_splits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gunicorn uses `shlex.split`, so a quoted value is still a number. Plain
    `str.split` would read `"2"` with its quotes and report nothing."""
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    monkeypatch.setenv("GUNICORN_CMD_ARGS", '--workers "2"')
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert _configured_worker_count()[0] == "2"


def test_unbalanced_quoting_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    monkeypatch.setenv("GUNICORN_CMD_ARGS", '--workers "2')
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert _configured_worker_count() == ("1", "WEB_CONCURRENCY=1")


def test_a_config_file_launch_says_unknown_rather_than_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The blind spot must not be reported as a verified single worker."""
    monkeypatch.setattr("sys.argv", ["gunicorn", "-c", "gunicorn.conf.py"])
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    count, source = _configured_worker_count()
    assert count == "unknown"
    assert "config file" in source


def test_a_non_gunicorn_launch_ignores_gunicorn_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python web/api/app.py --workers 2` runs Flask's development server,
    which ignores the flag. Warning about it would be a false alarm."""
    monkeypatch.setattr("sys.argv", ["web/api/app.py", "--workers", "2"])
    monkeypatch.setenv("GUNICORN_CMD_ARGS", "--workers=4")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert _configured_worker_count() == ("1", "WEB_CONCURRENCY=1")


def test_web_concurrency_still_answers_when_nothing_else_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert _configured_worker_count() == ("4", "WEB_CONCURRENCY=4")


def test_web_concurrency_is_compared_as_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WEB_CONCURRENCY=01` is one worker, and must not warn."""
    monkeypatch.setattr("sys.argv", ["gunicorn"])
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "01")
    assert _configured_worker_count()[0] == "1"


def test_a_single_worker_launch_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["gunicorn", "--workers", "1", "--threads", "8"])
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert _configured_worker_count()[0] == "1"


def _warnings_from_a_launch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, argv: list[str]
) -> list[str]:
    from web.api.app import create_app

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
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
    """A config-file launch must produce the "cannot verify" warning, not
    silence — silence is what a fabricated "1" would buy."""
    warnings = _warnings_from_a_launch(monkeypatch, caplog, ["gunicorn", "-c", "gunicorn.conf.py"])
    cannot_verify = [m for m in warnings if "Cannot verify" in m]
    assert cannot_verify, f"no cannot-verify warning in {warnings}"
    assert "config file" in cannot_verify[0]
