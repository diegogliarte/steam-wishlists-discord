# Steam Wishlist Discord

Keeps one Discord message updated with your Steam wishlist total and the last 7 days of changes.

## Install

```bash
sudo ./install.sh
nano /opt/steam-wishlist-discord/.env
python3 /opt/steam-wishlist-discord/wishlist_bot.py
```

The installer adds an hourly cron job automatically.

## Update

```bash
git pull
sudo ./install.sh
```

`.env` and `state.json` are preserved between updates.
