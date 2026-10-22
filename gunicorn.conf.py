# The one gunicorn setting that must be under review, in git. Discovered
# automatically because systemd's WorkingDirectory is this directory
# (gunicorn/config.py:583 resolves './gunicorn.conf.py' against the launch cwd).
#
# Do NOT also put --workers in the systemd ExecStart: command-line settings are
# applied last (gunicorn/app/base.py:189) and silently win, which is how this
# drifted to 2 for months unreviewed.
workers = 1  # MUST be 1 — see _MULTI_WORKER_COST in web/api/app.py
raw_env = [f"SFDA_CONFIG_WORKERS={workers}"]

# gunicorn 25.1+ opens a control socket that `gunicornc` can use to change the
# worker count at runtime — a path around the line above that nothing reviews.
# It also fails on the VPS (www-data's $HOME, /var/www, is root-owned), logging
# "Control server error: Permission denied: '/var/www/.gunicorn'" at every boot.
# Older gunicorn ignores the unknown name (gunicorn/app/base.py:139-141), so the
# 23.0.0 rollback venv still reads this file.
control_socket_disable = True
