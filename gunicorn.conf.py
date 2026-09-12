# The one gunicorn setting that must be under review, in git. Discovered
# automatically because systemd's WorkingDirectory is this directory
# (gunicorn/config.py:583 resolves './gunicorn.conf.py' against the launch cwd).
#
# Do NOT also put --workers in the systemd ExecStart: command-line settings are
# applied last (gunicorn/app/base.py:189) and silently win, which is how this
# drifted to 2 for months unreviewed.
workers = 1  # MUST be 1 — see _MULTI_WORKER_COST in web/api/app.py:370
raw_env = [f"SFDA_CONFIG_WORKERS={workers}"]
