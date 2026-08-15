# Steam Wishlists Discord

Keeps one Discord message updated with your Steam wishlist total, 7-day change and 30-day change.

## Install

```bash
sudo git clone https://github.com/diegogliarte/steam-wishlists-discord.git /opt/steam-wishlists-discord
cd /opt/steam-wishlists-discord
sudo ./install.sh
nano .env
python3 wishlists_bot.py
```

The game name is fetched automatically from Steam. Runs every hour with cron.

## Update

```bash
cd /opt/steam-wishlists-discord
git pull
```
