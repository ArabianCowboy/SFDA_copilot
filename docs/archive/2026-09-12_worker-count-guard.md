---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-12
supersedes_note: >
  A finished plan. Every step in it was built, committed and deployed to production
  on the day it was written, so its own "STATUS: PROPOSAL - nothing here is built"
  line was already false when it was archived. Three of its verdicts reversed
  earlier drafts and are marked REVERSED in place; two further corrections arrived
  after it was written and are stated below.
live_authority:
  - docs/OPERATIONS.md
  - docs/ARCHITECTURE.md
  - deploy/sfda-copilot.service
  - gunicorn.conf.py
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/OPERATIONS.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.
>
> **Final position, so no reading order is required.** All of this shipped on
> 2026-09-12 and is live: the guard was rewritten (`_configured_worker_count` in
> `web/api/app.py`), `_gunicorn_config_file_in_play` was deleted, `gunicorn.conf.py`
> was committed at the repo root, and `--workers` was removed from the production
> `ExecStart`. Verified on the box - no `--workers` in the running command line, one
> master plus one worker, HTTPS 200, `NRestarts=0`.
>
> **Reversed after this was written - the systemd unit IS in version control.** §2
> argues it cannot be, and that `docs/OPERATIONS.md` should carry a transcript of it
> instead. Overturned the same day: host-specific paths stop a committed unit from
> being _applied_ automatically, they do not stop it being _reviewed_, and a
> hand-copied transcript drifts exactly the way `--workers` drifted. The unit is now
> at `deploy/sfda-copilot.service`, byte-identical to the live file, and
> `OPERATIONS.md` points at it rather than restating it.
>
> **Corrected after this was written - `--chdir` plays NO part in config discovery.**
> §2 says discovery follows the launch cwd rather than the `--chdir` target. Measured
> on the box, `--chdir` contributes nothing at all, and `--print-config` reports
> `config = ./gunicorn.conf.py` either way - only `raw_env` distinguishes them.
> `WorkingDirectory=` is the load-bearing line and must never be removed.

# [HISTORICAL] Fixing the single-worker startup guard

STATUS: PROPOSAL 2026-09-12 — nothing here is built. Written against `a482614`, which shipped
the guard this plan corrects. Three verdicts in here are **REVERSED** from earlier drafts and
are marked as such; they were reached before the production `systemd` unit had been read, and
were wrong. Reviewed by `gpt-5.6-sol` and `opencode/muse-spark-1.3`; every gunicorn citation
below was read from the installed sources, not recalled.

---

## [HISTORICAL] 1. Why this exists

The app must run single-worker: the in-RAM FAISS index, `ConversationStore`,
`_InFlightGenerations`, `IdentityFlagsCache` and Flask-Limiter's counters are all
process-local (`_MULTI_WORKER_COST`, `web/api/app.py:370`).

Production ran **two** workers for months and the startup guard never fired, because the guard
read only `WEB_CONCURRENCY` while the real count came from gunicorn's `--workers 2`. Commit
`a482614` answered that by inferring the count from inside the process
(`_worker_count_from_argv` at `web/api/app.py:381`, `_gunicorn_config_file_in_play` at `:418`,
`_configured_worker_count` at `:436`).

Three reviews of `a482614` produced 15 findings. This plan closes the ones worth closing, in
**fewer lines than it deletes**.

Two things to hold onto, because they decide every trade below:

- **The root cause is an unversioned `ExecStart`.** The guard only _warns_, into a log nobody
  read for months. Step 0 is the only step that touches the cause.
- **A guard that warns on a correct configuration is worthless.** Every design here is judged
  on whether a correctly-configured production box boots **silently**.

---

## [HISTORICAL] 2. What the VPS reading changed

The production unit, read 2026-09-12:

```ini
[Service]
User=www-data
WorkingDirectory=/var/www/sfda-copilot
Environment=PATH=/var/www/sfda-copilot/venv/bin
EnvironmentFile=/var/www/sfda-copilot/.env
ExecStart=/var/www/sfda-copilot/venv/bin/gunicorn --bind 127.0.0.1:5001 \
  --workers 1 --threads 8 --preload --max-requests 1000 --max-requests-jitter 100 \
  --chdir /var/www/sfda-copilot web.api.app:create_app()
Restart=always
RestartSec=10
Environment=BEHIND_PROXY=true
```

No `.service.d/` drop-in. No `GUNICORN_CMD_ARGS`. No `WEB_CONCURRENCY` — not in `.env`, not in
the master's `/proc/<pid>/environ`. Deployment is `git pull` **into** `/var/www/sfda-copilot`,
which is the live working tree. Production runs gunicorn **23.0.0**; this dev tree has **26.0.0**.

| Fact                                        | Consequence                                                                                                                         |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `WorkingDirectory=/var/www/sfda-copilot`    | gunicorn's launch cwd **is** the repo root, so a committed `gunicorn.conf.py` _is_ discovered.                                      |
| `--chdir` targets that same directory       | Launch cwd and `--chdir` target coincide, so finding F3 cannot bite on this box.                                                    |
| Deployment is `git pull` into the live tree | A committed config file arrives with no new deploy machinery.                                                                       |
| `EnvironmentFile=.env`                      | `systemd` injects `.env` **before** gunicorn starts, so gunicorn and the app see the same values. F15 is real but cannot bite here. |

### [HISTORICAL] REVERSED — F9: "ship a `gunicorn.conf.py`" was rejected on a false premise

Both earlier reviews rejected a committed `gunicorn.conf.py` because `systemd` supposedly
starts from `/`, so cwd-based discovery (`gunicorn/config.py:583`) would never find a repo-root
file. **`WorkingDirectory=` is the repo root.** The premise was false, and the VPS admin
verified discovery empirically on the box's own gunicorn 23.0.0.

The rejection's second leg survives and shapes step 0: command-line settings are applied last
(`gunicorn/app/base.py:189`, "Lastly, update the configuration with any command line settings"),
verified on the box — `workers = 7` in the file plus `--workers 1` on the CLI resolved to **1**.

### [HISTORICAL] REVERSED — F3: real mechanism, unreachable here

`gunicorn/app/base.py:163` calls `self.chdir()` while `cfg.chdir` is still its default (the
launch cwd, `config.py:1103`), _then_ discovers the config file at `:177`, and only applies
`--chdir` at `:189`. So the app's `os.getcwd()` probe at `web/api/app.py:433` reads the
post-`--chdir` directory while gunicorn searched the pre-`--chdir` one. On this deployment
those are the same directory. The probe is still deleted (step 1) — not for F3, but because
once `gunicorn.conf.py` exists in the repo root the probe returns `True` on every run
everywhere, permanently forcing `"unknown"`.

### [HISTORICAL] REVERSED — an earlier draft of step 0 would have warned on every boot, forever

`muse-spark-1.3` caught this and it is the most important finding in the review. A draft of
step 0 removed `--workers 1` from `ExecStart` and put `workers = 1` in the config file. But the
step 1 guard cannot read a config file, so the resulting production shape — no `--workers`, no
`GUNICORN_CMD_ARGS`, no `WEB_CONCURRENCY` — resolves to `"unknown"`, and `create_app`
(`web/api/app.py:2549-2555`) logs **"Cannot verify the single-worker requirement" on every boot
of a correctly-configured box**. That is the cry-wolf disease this plan exists to cure,
re-introduced by the cure.

`muse-spark-1.3`'s proposed escape was to keep `--workers 1` on the command line _as well as_
in the file — but then the file is inert (the CLI wins) and the root cause is untouched. §3
step 0 takes a third route instead: the config file **declares its own resolved count into the
environment**, where the guard can read it without executing anything.

### [HISTORICAL] Not a bug: the archive salts

The VPS reading flagged `ARCHIVE_OWNER_SALT`/`ARCHIVE_SESSION_SALT` as unset, "so the archive
is silently off in production." That is the intended, documented state. `README.md:243-244`
says "leave unset"; `web/config.yaml:74-88` records that the opt-out toggle, withdrawal column,
purge RPC, retention CLI and export were all **cut** on that basis, and that setting either
salt "starts collecting text the reader was never told about."
`_warn_if_archive_is_undisclosed` (`web/api/app.py:1720`, salts read at `:1747`) exists to
refuse exactly that. No action — **do not set them without reading that guard first.**

---

## [HISTORICAL] 3. The plan

### [HISTORICAL] Step 0 — ops, on the VPS (the only step that addresses the root cause)

Commit `gunicorn.conf.py` to the repo root. **Two lines:**

```python
# The one gunicorn setting that must be under review, in git. Discovered
# automatically because systemd's WorkingDirectory is this directory
# (gunicorn/config.py:583 resolves './gunicorn.conf.py' against the launch cwd).
#
# Do NOT also put --workers in the systemd ExecStart: command-line settings are
# applied last (gunicorn/app/base.py:189) and silently win, which is how this
# drifted to 2 for months unreviewed.
workers = 1  # MUST be 1 — see _MULTI_WORKER_COST in web/api/app.py:370
raw_env = [f"SFDA_CONFIG_WORKERS={workers}"]
```

Then delete **only** `--workers 1` from `ExecStart`, leaving every other flag untouched:

```ini
ExecStart=/var/www/sfda-copilot/venv/bin/gunicorn --bind 127.0.0.1:5001 \
  --threads 8 --preload --max-requests 1000 --max-requests-jitter 100 \
  --chdir /var/www/sfda-copilot web.api.app:create_app()
```

Back up the unit first, `daemon-reload`, restart, re-verify one master plus one worker and a
`127.0.0.1:5001` bind.

**Why `raw_env` — this is what makes the whole plan cohere.** `Arbiter.setup()` applies
`cfg.env` to `os.environ` at `arbiter.py:133-136`, **immediately before** it imports the app
under `--preload` at `:138` (and before workers are forked at `:694` without preload). So a
config file can hand the app a value, and `Config.env` (`config.py:208-215`) parses the
`raw_env` setting (`config.py:1131`) into exactly that. Deriving the string from `workers`
rather than typing `1` twice means the declaration **cannot drift from the setting it
declares**. Result: a correctly-configured production box reports `"1"` and boots silently,
while the count still lives in a reviewed, diffed, `git pull`-deployed file.

It survives the drift this plan exists for. If someone re-adds `--workers 2` to `ExecStart`,
gunicorn uses 2 _and_ the guard reads the command line first — so it reports 2 and warns.

**It is an attestation, not a measurement, and the difference matters.** `gpt-5.6-terra`
was right to push back on an earlier draft that called it un-lie-able. `SFDA_CONFIG_WORKERS`
is an ordinary environment variable, so systemd `Environment=`/`EnvironmentFile=`, a launcher
wrapper, `--env`, or an alternate `-c` config can all set it, and the guard does not verify
that the marker came from the configuration that actually resolved `workers`. A stale or
mistaken `SFDA_CONFIG_WORKERS=1` alongside an opaque config selecting more workers would
silence the warning — where the deleted probe would at least have said `"unknown"`. That is
not remotely exploitable (it needs prior control of the service configuration), but it is an
operational footgun, and it is the price of deleting the probe. **The honest conclusion: this
guard is a cheap in-process smoke alarm, not evidence.** Anything that needs to _know_ the
running worker count should count processes from outside — see §4.3.

**Why `--chdir` stays.** `Application.chdir()` (`gunicorn/app/base.py:83-90`) does two things:

```python
os.chdir(self.cfg.chdir)
if self.cfg.chdir not in sys.path:
    sys.path.insert(0, self.cfg.chdir)
```

That `sys.path.insert` is what makes `web.api.app:create_app()` importable
(`util.import_app`, `util.py:403`). Removing `--chdir` would still work — `Chdir.default =
util.getcwd()` (`config.py:1103`) resolves to the same directory under `WorkingDirectory=`, and
the first `chdir()` at `:163` precedes the import — but only via a default evaluated at
gunicorn's import time that silently depends on `WorkingDirectory=` never being removed.
`--chdir` cannot drift dangerously; `--workers` can. Move the one flag that caused the outage.

### [HISTORICAL] Step 1 — rewrite the guard (`web/api/app.py`)

At module top level, **after** the `dotenv_values(...)` read at `:129` and **before** the
`load_dotenv(...)` call at `:131` (`dotenv_values` is side-effect-free, which is why that gap
is the right place):

```python
_LAUNCH_ENV = {
    k: os.getenv(k)
    for k in ("SERVER_SOFTWARE", "GUNICORN_CMD_ARGS", "SFDA_CONFIG_WORKERS", "WEB_CONCURRENCY")
}
```

Add one helper, and make `_worker_count_from_argv` use it so the coercion exists once:

```python
def _as_count(value: str | None) -> str | None:
    """Canonical decimal, or None. `01` must read as one worker, not two."""
    try:
        return str(int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
```

Replace `_configured_worker_count` (`:436-484`) and **delete `_gunicorn_config_file_in_play`
entirely** (`:418-433`):

```python
def _configured_worker_count() -> tuple[str, str]:
    """Return (worker count, where it was set), for the single-worker warning.

    Gunicorn-only by construction. `Arbiter.__init__` sets SERVER_SOFTWARE
    (arbiter.py:54) before it imports this app under --preload (arbiter.py:138),
    and forked workers inherit it, so it is a reliable marker and — unlike
    argv[0] — survives `python -m gunicorn`.

    Sources are tried in gunicorn's own precedence order (app/base.py:172-195).
    Every value comes from the snapshot taken before `load_dotenv`: gunicorn
    resolves `workers` at import time (config.py:690) and parses
    GUNICORN_CMD_ARGS at base.py:170, both before this module loads, so a value
    that reached the process only via python-dotenv is one gunicorn never saw.

    SFDA_CONFIG_WORKERS is how `gunicorn.conf.py` declares itself; see that file.
    Reading the config file directly is not an option — gunicorn *executes* it
    (app/base.py:110), and re-running it here would duplicate its side effects.

    Two things it cannot see, stated rather than guessed at: a count changed
    after startup by signalling the master (TTIN/TTOU), and any non-gunicorn
    host. It infers the configured count; it does not measure the running one.
    """
    argv0 = os.path.basename(sys.argv[0]).lower() if sys.argv else ""
    if not (
        (_LAUNCH_ENV["SERVER_SOFTWARE"] or "").lower().startswith("gunicorn/")
        or "gunicorn" in argv0
    ):
        return "1", "not a gunicorn launch"

    try:
        cmd_args = shlex.split(_LAUNCH_ENV["GUNICORN_CMD_ARGS"] or "")
    except ValueError:
        return "unknown", "GUNICORN_CMD_ARGS cannot be parsed"

    for source, count in (
        ("the command line", _worker_count_from_argv(sys.argv[1:])),
        ("GUNICORN_CMD_ARGS", _worker_count_from_argv(cmd_args)),
        ("gunicorn.conf.py", _as_count(_LAUNCH_ENV["SFDA_CONFIG_WORKERS"])),
        ("WEB_CONCURRENCY", _as_count(_LAUNCH_ENV["WEB_CONCURRENCY"])),
    ):
        if count:
            return count, f"{source} sets {count} workers"

    return "unknown", "gunicorn names no worker count this check can read"
```

**Four sources, one loop, one table.** They differ only by a label, so they are data. The
`WEB_CONCURRENCY` row is kept deliberately — `muse-spark-1.3` was right that the
`SERVER_SOFTWARE` gate alone removes every false alarm F4 complained about, so dropping the
row would throw away a real signal on container hosts where that variable is the only
interface, for no gain.

`"1", "not a gunicorn launch"` stays silent for the dev server and pytest, which is the F4 fix.
It does overclaim on a hypothetical multi-process non-gunicorn host (uWSGI, mod_wsgi) — the
shipped code has the same hole, this repo documents no such host, and `"unknown"` there would
warn on every `python web/api/app.py`. Accepted, and now written down.

**Closes:** F1 (`SERVER_SOFTWARE` survives `python -m gunicorn`), F2 and F7 (the unanswerable
probe is deleted rather than answered wrongly), F3 (no `os.getcwd()` read at all), F4
(gunicorn-gated), F8 (no probe for tests to depend on), F15 (pre-dotenv snapshot).

**Net lines:** deletes `_gunicorn_config_file_in_play` (16) and its tests (~40); adds ~28 in
`app.py` and 2 in `gunicorn.conf.py`. Roughly **−56 / +30**.

**Rejected, so nobody re-derives them:** reusing `Config().parser()` (`config.py:9` imports
`grp`/`pwd`, absent on Windows — it would break every dev machine here; no stability contract;
can exit through `argparse`); importing or scanning the config file (gunicorn executes it,
`app/base.py:110`); and using an `on_starting`/`when_ready` hook to publish the count — dead,
because under `--preload` the app is imported at `arbiter.py:138` inside `setup()`, called from
`__init__` at `:63`, _before_ `on_starting` at `:162`. `raw_env` at `:133-136` is the only hook
that runs early enough.

### [HISTORICAL] Step 2 — tests (`web/tests/test_worker_count_guard.py`)

**The one thing an implementer will get wrong.** The snapshot is taken at module import, so
`monkeypatch.setenv("SERVER_SOFTWARE", …)` is a **no-op** for this function. Every test must
patch the dict entry instead:

```python
monkeypatch.setitem(app_module._LAUNCH_ENV, "SERVER_SOFTWARE", "gunicorn/26.0.0")
```

Delete every `_gunicorn_config_file_in_play` test along with the function. Rework the existing
`GUNICORN_CMD_ARGS` tests at `:117-143` onto `setitem` — they currently use `setenv` and would
silently pass against a stale snapshot. The unbalanced-quoting test at `:139` keeps its name
but changes expectation to `("unknown", "GUNICORN_CMD_ARGS cannot be parsed")`. The
`WEB_CONCURRENCY` tests at `:169`/`:178` survive, moved onto `setitem` and with a
`SERVER_SOFTWARE` entry added.

Add, all of which must fail against `a482614`:

| Test                                                                                   | Asserts                                      |
| -------------------------------------------------------------------------------------- | -------------------------------------------- |
| `python -m gunicorn` + `--workers 2`, `SERVER_SOFTWARE` set                            | `"2"` — argv0 is `__main__.py`               |
| Dev server, no `SERVER_SOFTWARE`, `WEB_CONCURRENCY=4`                                  | `("1", "not a gunicorn launch")`             |
| `SFDA_CONFIG_WORKERS=1`, nothing else                                                  | `("1", "gunicorn.conf.py sets 1 workers")`   |
| `SFDA_CONFIG_WORKERS=4` + `--workers 1`                                                | `"1"` — command line wins, matching gunicorn |
| `os.getcwd` monkeypatched to **raise**                                                 | passes — proves the probe is gone            |
| **The post-step-0 production line**, bare of `--workers`, plus `SFDA_CONFIG_WORKERS=1` | `"1"` — the box boots silently               |

Fix the false comment at `:35`: that vector is `0.0.0.0`, 2 workers, 2 threads, no
`--max-requests`, no `--chdir` — the **drifted** line, not "the real production line, verbatim
apart from the paths" (F13). Keep it, relabelled as the regression vector.

### [HISTORICAL] Step 3 — documents, same commit

| File                               | Change                                                                                                                                                                                                                                               | Finding |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `README.md:99` and `:253`          | Describe the four sources and the gunicorn-only gate; `WEB_CONCURRENCY` still warns, so that row stands — but add `gunicorn.conf.py`.                                                                                                                | F4      |
| `docs/ARCHITECTURE.md`             | Same, plus: `gunicorn.conf.py` owns the worker count and `--workers` in `ExecStart` overrides it.                                                                                                                                                    | F4, F9  |
| `docs/OPERATIONS.md`               | The full unit verbatim, the `WorkingDirectory`/`EnvironmentFile` facts, the gunicorn 23.0.0-vs-26.0.0 divergence, and the rule that `ExecStart` must not name `--workers`.                                                                           | F9      |
| `web/api/auth.py:53`               | "every number below" → "every number **above**" (the 10/50/200 figures are at `:41-42`).                                                                                                                                                             | F12     |
| `TODO.md`                          | Lift the still-owed signed-in streaming check out of the archive.                                                                                                                                                                                    | F10     |
| `docs/archive/TODO-resolved.md:80` | Replace the open item with a historical note saying it was lifted. Editing a resolved entry in place is permitted here because the archive procedure governs _adding_ plans; this only removes an instruction the archive should never have carried. | F10     |
| `docs/archive/README.md:50`        | `36` → **`39`**. Verified: 38 headings at `HEAD^`, 39 now.                                                                                                                                                                                           | F11     |

On F10: the VPS reading is strong circumstantial evidence streaming works —
`web/services/sse.py:34` sets `X-Accel-Buffering: no`, the vhost sets no `proxy_buffering off`,
`gzip_types` excludes `text/event-stream`, and the access log shows a signed-in
`POST /api/chat/stream` returning 200 with 14,994 bytes delivered while the journal logs
`Client disconnected mid-stream` ~6s in. Bytes reached the browser mid-generation, which
buffering would have prevented. That is inference from logs, not the direct check, so the
`TODO.md` entry stays open.

### [HISTORICAL] Step 4 — deliberately not doing

- **Pinning `gunicorn`** (F14). After step 1 the guard imports nothing from gunicorn, and every
  other line in `requirements.txt` is unpinned. **But see §4.1** — it deserves its own decision.
- **Any F5 fix.** CPython guarantees a non-empty `sys.argv`; the premise was wrong. The
  `if sys.argv else ""` is free, so it is there anyway.
- **Making the warning fatal.** With `Restart=always`/`RestartSec=10` that converts drift into
  a restart loop.
- **TTIN/TTOU.** Needs runtime supervision, not configuration inference.

---

## [HISTORICAL] 4. Separate decisions this turned up

1. **Production runs gunicorn 23.0.0; this dev tree has 26.0.0** — same unpinned
   `requirements.txt`, two majors apart. Every citation here was read from 26.0.0; the two
   behaviours that matter were re-verified empirically on 23.0.0. This is a stronger argument
   for pinning than anything in the findings.
2. **Production is 8 commits behind `origin/main`** (last fetch 2026-09-07). Undeployed:
   `fix(chat): refuse and refund an empty answer on both chat routes`, `fix(chat): tell the
reader when an answer was cut short`, `fix(auth): bind logout revocation to the caller`.
3. **The warning is only ever logged.** The drift survived months because nobody read the log.
   `/admin` overview is read; surfacing the resolved worker count there would put it in front
   of the one person who acts on it.
4. **Two accepted divergences from `docs/ARCHITECTURE.md`**, neither caused by this work: no
   `--timeout` in the unit (gunicorn's 30s default applies; the document says 300), and
   `--max-requests 1000` on a single worker leaves a sub-second gap while the replacement forks.
5. **`Environment=BEHIND_PROXY=true` is redundant** — `.env` already sets it via
   `EnvironmentFile=`.

---

## [HISTORICAL] 5. Repo obligations this triggers

- **No `APP_VERSION` bump** (`web/api/app.py:313`) — `CLAUDE.md` rule 9 fires only on edits to
  `CLAUDE.md` itself, and there are none.
- **No `ASSET_VERSION` bump** (`:307`) — no CSS or JS changes.
- **No i18n work** — no new UI strings, so `en.yaml`/`ar.yaml` parity is untouched.
- **The new repo-root `gunicorn.conf.py` falls under `ruff` and `pre-commit`** — it must pass
  `ruff check` and `ruff format` like any other Python file.
- **The same-commit documentation rule applies**: step 3 ships with steps 1 and 2.
