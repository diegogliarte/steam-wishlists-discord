#!/usr/bin/env python3
"""Keep one Discord webhook message updated with Steam wishlist stats."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "state.json"
WISHLIST_ENDPOINT = (
    "https://partner.steam-api.com/"
    "IPartnerFinancialsService/GetAppWishlistReporting/v001/"
)
APP_DETAILS_ENDPOINT = "https://store.steampowered.com/api/appdetails"
USER_AGENT = "steam-wishlists-discord/1.3"
EMBED_COLOR = 0x9471ED


def load_dotenv(path: Path) -> None:
    """Load a small .env file without requiring python-dotenv."""
    if not path.exists():
        raise FileNotFoundError(path)

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        if key:
            os.environ.setdefault(key, value)


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default.copy()
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    temp.replace(path)


def http_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {"User-Agent": USER_AGENT}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def steam_day(api_key: str, app_id: int, day: date) -> dict[str, Any]:
    query = urlencode({"key": api_key, "appid": app_id, "date": day.isoformat()})
    data = http_json(f"{WISHLIST_ENDPOINT}?{query}")
    return data.get("response", {})


def steam_app_name(app_id: int, state: dict[str, Any]) -> str:
    """Fetch the public Steam Store name, falling back to the cached name."""
    query = urlencode({"appids": app_id, "l": "english"})

    try:
        data = http_json(f"{APP_DETAILS_ENDPOINT}?{query}")
        app = data.get(str(app_id), {})
        if isinstance(app, dict) and app.get("success"):
            details = app.get("data", {})
            if isinstance(details, dict):
                name = str(details.get("name", "")).strip()
                if name:
                    state["app_name"] = name
                    return name
    except (RuntimeError, ValueError, TypeError) as exc:
        print(f"Could not refresh app name: {exc}", file=sys.stderr)

    cached_name = str(state.get("app_name", "")).strip()
    if cached_name:
        return cached_name

    raise RuntimeError(f"Steam Store did not return a name for AppID {app_id}.")


def normalize_day(response: dict[str, Any]) -> dict[str, int] | None:
    summary = response.get("wishlist_summary")
    if not isinstance(summary, dict):
        return None

    return {
        "adds": int(summary.get("wishlist_adds", 0)),
        "deletes": int(summary.get("wishlist_deletes", 0)),
        "purchases": int(summary.get("wishlist_purchases", 0)),
        "gifts": int(summary.get("wishlist_gifts", 0)),
    }


def net_change(stats: dict[str, int]) -> int:
    return (
        stats.get("adds", 0)
        - stats.get("deletes", 0)
        - stats.get("purchases", 0)
        - stats.get("gifts", 0)
    )


def parse_iso_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def day_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def latest_closed_gmt_day() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def update_cache(api_key: str, app_id: int, state: dict[str, Any]) -> None:
    target = latest_closed_gmt_day()
    days: dict[str, dict[str, int]] = state.setdefault("days", {})

    print(f"Checking Steam data through {target.isoformat()}...")

    probe = steam_day(api_key, app_id, target)
    app_min_date = probe.get("app_min_date") or state.get("app_min_date")
    if not app_min_date:
        raise RuntimeError("Steam did not return app_min_date.")

    start = parse_iso_day(str(app_min_date))
    state["app_min_date"] = start.isoformat()

    probe_stats = normalize_day(probe)
    if probe_stats is not None:
        days[target.isoformat()] = probe_stats
        save_json(STATE_PATH, state)

    missing = [d for d in day_range(start, target) if d.isoformat() not in days]
    if missing:
        print(f"Fetching {len(missing)} missing day(s)...")

    for index, day in enumerate(missing, start=1):
        response = steam_day(api_key, app_id, day)
        stats = normalize_day(response)
        if stats is not None:
            days[day.isoformat()] = stats
            save_json(STATE_PATH, state)

        if index % 25 == 0 or index == len(missing):
            print(f"  {index}/{len(missing)}")

        time.sleep(0.08)


def signed(value: int) -> str:
    return f"{value:+,d}"


def period_change(
    days: dict[str, dict[str, int]],
    latest: date,
    count: int,
) -> int:
    return sum(
        net_change(days.get((latest - timedelta(days=i)).isoformat(), {}))
        for i in range(count)
    )


def build_embed(state: dict[str, Any], app_id: int, app_name: str) -> dict[str, Any]:
    days: dict[str, dict[str, int]] = state.get("days", {})
    if not days:
        raise RuntimeError("No wishlist data is cached yet.")

    ordered_dates = sorted(days)
    latest = parse_iso_day(ordered_dates[-1])
    total = sum(net_change(stats) for stats in days.values())
    seven_day_total = period_change(days, latest, 7)
    thirty_day_total = period_change(days, latest, 30)

    # Latest available Steam day first, then -1 day, -2 days, etc.
    recent = [
        (
            latest - timedelta(days=i),
            net_change(days.get((latest - timedelta(days=i)).isoformat(), {})),
        )
        for i in range(7)
    ]
    daily_lines = [
        f"{day.strftime('%b %d'):<8}{signed(value):>8}"
        for day, value in recent
    ]

    return {
        "title": app_name,
        "url": f"https://store.steampowered.com/app/{app_id}/",
        "description": "Steam wishlist overview",
        "color": EMBED_COLOR,
        "fields": [
            {
                "name": "Total wishlists",
                "value": f"**{total:,}**",
                "inline": True,
            },
            {
                "name": "Last 7 days",
                "value": f"**{signed(seven_day_total)}**",
                "inline": True,
            },
            {
                "name": "Last 30 days",
                "value": f"**{signed(thirty_day_total)}**",
                "inline": True,
            },
            {
                "name": "Daily change",
                "value": "```text\n" + "\n".join(daily_lines) + "\n```",
                "inline": False,
            },
        ],
        "footer": {"text": f"Steam data through {latest.strftime('%d %b %Y')} GMT"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def discord_payload(embed: dict[str, Any]) -> dict[str, Any]:
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


def create_discord_message(webhook_url: str, payload: dict[str, Any]) -> str:
    separator = "&" if "?" in webhook_url else "?"
    response = http_json(
        f"{webhook_url}{separator}wait=true",
        method="POST",
        payload=payload,
    )
    message_id = response.get("id")
    if not message_id:
        raise RuntimeError("Discord did not return a message ID.")
    return str(message_id)


def edit_discord_message(
    webhook_url: str,
    message_id: str,
    payload: dict[str, Any],
) -> None:
    url = webhook_url.rstrip("/") + f"/messages/{message_id}"
    http_json(url, method="PATCH", payload=payload)


def update_discord(
    webhook_url: str,
    state: dict[str, Any],
    app_id: int,
    app_name: str,
) -> None:
    payload = discord_payload(build_embed(state, app_id, app_name))
    message_id = state.get("discord_message_id")

    if message_id:
        try:
            edit_discord_message(webhook_url, str(message_id), payload)
            print(f"Updated Discord message {message_id}.")
            return
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            print("Discord message was deleted; creating a new one.")

    message_id = create_discord_message(webhook_url, payload)
    state["discord_message_id"] = message_id
    save_json(STATE_PATH, state)
    print(f"Created Discord message {message_id}.")


def read_config() -> tuple[str, int, str]:
    load_dotenv(ENV_PATH)

    api_key = os.environ.get("STEAM_API_KEY", "").strip()
    app_id_raw = os.environ.get("STEAM_APP_ID", "").strip()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    missing = [
        name
        for name, value in (
            ("STEAM_API_KEY", api_key),
            ("STEAM_APP_ID", app_id_raw),
            ("DISCORD_WEBHOOK_URL", webhook_url),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing .env value(s): " + ", ".join(missing))

    try:
        app_id = int(app_id_raw)
    except ValueError as exc:
        raise RuntimeError("STEAM_APP_ID must be a number.") from exc

    if (
        "discord.com/api/webhooks/" not in webhook_url
        and "discordapp.com/api/webhooks/" not in webhook_url
    ):
        raise RuntimeError("DISCORD_WEBHOOK_URL does not look like a Discord webhook URL.")

    return api_key, app_id, webhook_url


def main() -> int:
    if not ENV_PATH.exists():
        print(".env is missing. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2

    try:
        api_key, app_id, webhook_url = read_config()
        state = load_json(STATE_PATH, {"days": {}})
        app_name = steam_app_name(app_id, state)
        print(f"App: {app_name} ({app_id})")
        update_cache(api_key, app_id, state)
        update_discord(webhook_url, state, app_id, app_name)
        save_json(STATE_PATH, state)
        return 0
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
