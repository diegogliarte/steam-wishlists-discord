#!/usr/bin/env bash
set -euo pipefail

APP_NAME="steam-wishlists-discord"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$ROOT/wishlists_bot.py"
ENV_FILE="$ROOT/.env"
CRON_FILE="/etc/cron.d/$APP_NAME"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo ./install.sh" >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-}"
if [[ -z "$RUN_USER" || "$RUN_USER" == "root" ]]; then
  echo "Run this from your normal user with sudo." >&2
  exit 1
fi

RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON="$(command -v python3 || true)"

if [[ -z "$PYTHON" ]]; then
  echo "python3 is required." >&2
  exit 1
fi

if [[ ! -f "$SCRIPT" ]]; then
  echo "Missing $SCRIPT" >&2
  exit 1
fi

# The repository in /opt is the live installation. Give it back to the
# invoking user so future `git pull` commands do not need sudo.
chown -R "$RUN_USER:$RUN_GROUP" "$ROOT"

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 -o "$RUN_USER" -g "$RUN_GROUP" \
    "$ROOT/.env.example" "$ENV_FILE"
  CREATED_ENV=1
else
  CREATED_ENV=0
  chown "$RUN_USER:$RUN_GROUP" "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
fi

"$PYTHON" -m py_compile "$SCRIPT"
rm -rf "$ROOT/__pycache__"

cat > "$CRON_FILE" <<EOF_CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""

0 * * * * $RUN_USER cd $ROOT && $PYTHON $SCRIPT >> $ROOT/wishlists.log 2>&1
EOF_CRON
chmod 0644 "$CRON_FILE"

echo "Hourly cron installed."

if [[ $CREATED_ENV -eq 1 ]]; then
  echo "Edit $ENV_FILE, then run:"
  echo "  $PYTHON $SCRIPT"
else
  echo "Existing .env preserved."
fi
