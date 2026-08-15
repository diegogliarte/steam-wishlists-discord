#!/usr/bin/env bash
set -euo pipefail

APP_NAME="steam-wishlists-discord"
INSTALL_DIR="${INSTALL_DIR:-/opt/$APP_NAME}"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo: sudo ./install.sh" >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-}"
if [[ -z "$RUN_USER" || "$RUN_USER" == "root" ]]; then
  RUN_USER="$(stat -c '%U' "$SOURCE_DIR")"
fi

if [[ -z "$RUN_USER" || "$RUN_USER" == "root" ]]; then
  echo "Could not determine the non-root user that should run the script." >&2
  exit 1
fi

RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON="$(command -v python3 || true)"

if [[ -z "$PYTHON" ]]; then
  echo "python3 is required." >&2
  exit 1
fi

install -d -m 0755 -o "$RUN_USER" -g "$RUN_GROUP" "$INSTALL_DIR"
install -m 0755 -o "$RUN_USER" -g "$RUN_GROUP" \
  "$SOURCE_DIR/wishlists_bot.py" "$INSTALL_DIR/wishlists_bot.py"
install -m 0644 -o "$RUN_USER" -g "$RUN_GROUP" \
  "$SOURCE_DIR/.env.example" "$INSTALL_DIR/.env.example"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  install -m 0600 -o "$RUN_USER" -g "$RUN_GROUP" \
    "$SOURCE_DIR/.env.example" "$INSTALL_DIR/.env"
  CREATED_ENV=1
else
  CREATED_ENV=0
fi

CRON_DIR="${CRON_DIR:-/etc/cron.d}"
CRON_FILE="$CRON_DIR/$APP_NAME"
install -d -m 0755 "$CRON_DIR"
cat > "$CRON_FILE" <<EOF_CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 * * * * $RUN_USER cd $INSTALL_DIR && $PYTHON wishlists_bot.py >> wishlists.log 2>&1
EOF_CRON
chmod 0644 "$CRON_FILE"

"$PYTHON" -m py_compile "$INSTALL_DIR/wishlists_bot.py"
rm -rf "$INSTALL_DIR/__pycache__"

echo "Installed to $INSTALL_DIR"
echo "Hourly cron installed at $CRON_FILE"

if [[ $CREATED_ENV -eq 1 ]]; then
  echo "Edit $INSTALL_DIR/.env, then run:"
  echo "  $PYTHON $INSTALL_DIR/wishlists_bot.py"
else
  echo "Existing .env preserved."
fi
