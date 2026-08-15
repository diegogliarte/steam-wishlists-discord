# Steam Wishlists Discord

Keeps one Discord message updated with your total Steam wishlists and the last 7 days of changes.

## Install

```bash
sudo git clone https://github.com/diegogliarte/steam-wishlists-discord.git /opt/steam-wishlists-discord
cd /opt/steam-wishlists-discord
sudo ./install.sh
nano .env
python3 wishlists_bot.py
```

Runs automatically every hour with cron.

## Update

```bash
cd /opt/steam-wishlists-discord
git pull
```
