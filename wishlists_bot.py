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

WISHLIST_ENDPOINT = "https://partner.steam-api.com/" "IPartnerFinancialsService/GetAppWishlistReporting/v001/"
APP_DETAILS_ENDPOINT = "https://store.steampowered.com/api/appdetails"

USER_AGENT = "steam-wishlists-discord"
EMBED_COLOR = 0x9471ED


def load_dotenv() -> None:
    if not ENV_PATH.exists():
        raise FileNotFoundError(ENV_PATH)

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].lstrip()

        if "=" not in line:
            continue

        key, value = (part.strip() for part in line.split("=", 1))

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        if key:
            os.environ.setdefault(key, value)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"days": {}}

    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any]) -> None:
    temp = STATE_PATH.with_suffix(".json.tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")

    temp.replace(STATE_PATH)


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
    query = urlencode(
        {
            "key": api_key,
            "appid": app_id,
            "date": day.isoformat(),
        }
    )

    return http_json(f"{WISHLIST_ENDPOINT}?{query}").get("response", {})


def steam_app_name(app_id: int, state: dict[str, Any]) -> str:
    query = urlencode({"appids": app_id, "l": "english"})

    try:
        data = http_json(f"{APP_DETAILS_ENDPOINT}?{query}")
        app = data.get(str(app_id), {})

        if isinstance(app, dict) and app.get("success"):
            details = app.get("data", {})

            name = str(details.get("name", "")).strip() if isinstance(details, dict) else ""

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
    return stats.get("adds", 0) - stats.get("deletes", 0) - stats.get("purchases", 0) - stats.get("gifts", 0)


def signed(value: int) -> str:
    return f"{value:+,d}"


def period_change(
    days: dict[str, dict[str, int]],
    end: date,
    count: int,
) -> int:
    return sum(
        net_change(
            days.get(
                (end - timedelta(days=i)).isoformat(),
                {},
            )
        )
        for i in range(count)
    )


def update_cache(
    api_key: str,
    app_id: int,
    state: dict[str, Any],
) -> None:
    today = datetime.now(timezone.utc).date()
    days: dict[str, dict[str, int]] = state.setdefault("days", {})

    print(f"Checking Steam data through {today.isoformat()}...")

    # Always refresh today because Steam updates the current day's data.
    response = steam_day(api_key, app_id, today)

    app_min_date = response.get("app_min_date") or state.get("app_min_date")

    if not app_min_date:
        raise RuntimeError("Steam did not return app_min_date.")

    start = date.fromisoformat(str(app_min_date))
    state["app_min_date"] = start.isoformat()

    stats = normalize_day(response)

    if stats is not None:
        days[today.isoformat()] = stats
        save_state(state)

    # Historical days are only fetched if they are missing.
    missing: list[date] = []
    current = start

    while current < today:
        if current.isoformat() not in days:
            missing.append(current)

        current += timedelta(days=1)

    if missing:
        print(f"Fetching {len(missing)} missing day(s)...")

    for index, day in enumerate(missing, start=1):
        stats = normalize_day(steam_day(api_key, app_id, day))

        if stats is not None:
            days[day.isoformat()] = stats
            save_state(state)

        if index % 25 == 0 or index == len(missing):
            print(f"  {index}/{len(missing)}")

        time.sleep(0.08)


def build_embed(
    state: dict[str, Any],
    app_id: int,
    app_name: str,
) -> dict[str, Any]:
    days: dict[str, dict[str, int]] = state.get("days", {})

    if not days:
        raise RuntimeError("No wishlist data is cached yet.")

    now = datetime.now(timezone.utc)
    today = now.date()
    today_key = today.isoformat()

    total = sum(net_change(stats) for day_key, stats in days.items() if day_key <= today_key)

    daily_lines = []

    for i in range(7):
        day = today - timedelta(days=i)
        change = net_change(days.get(day.isoformat(), {}))

        daily_lines.append(f"{day.strftime('%b %d'):<8}{signed(change):>8}")

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
                "value": f"**{signed(period_change(days, today, 7))}**",
                "inline": True,
            },
            {
                "name": "Last 30 days",
                "value": f"**{signed(period_change(days, today, 30))}**",
                "inline": True,
            },
            {
                "name": "Daily change",
                "value": ("```text\n" + "\n".join(daily_lines) + "\n```"),
                "inline": False,
            },
        ],
        "footer": {"text": (f"Steam data through " f"{today.strftime('%d %b %Y')} UTC")},
        "timestamp": now.isoformat(),
    }


def update_discord(
    webhook_url: str,
    state: dict[str, Any],
    app_id: int,
    app_name: str,
) -> None:
    payload = {
        "embeds": [
            build_embed(
                state,
                app_id,
                app_name,
            )
        ],
        "allowed_mentions": {
            "parse": [],
        },
    }

    message_id = state.get("discord_message_id")

    if message_id:
        try:
            url = webhook_url.rstrip("/") + f"/messages/{message_id}"

            http_json(
                url,
                method="PATCH",
                payload=payload,
            )

            print(f"Updated Discord message {message_id}.")
            return

        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise

            print("Discord message was deleted; " "creating a new one.")

    separator = "&" if "?" in webhook_url else "?"

    response = http_json(
        f"{webhook_url}{separator}wait=true",
        method="POST",
        payload=payload,
    )

    message_id = response.get("id")

    if not message_id:
        raise RuntimeError("Discord did not return a message ID.")

    state["discord_message_id"] = str(message_id)
    save_state(state)

    print(f"Created Discord message {message_id}.")


def read_config() -> tuple[str, int, str]:
    load_dotenv()
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

    if "discord.com/api/webhooks/" not in webhook_url and "discordapp.com/api/webhooks/" not in webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL does not look like " "a Discord webhook URL.")

    return api_key, app_id, webhook_url


def main() -> int:
    if not ENV_PATH.exists():
        print(
            ".env is missing. Copy .env.example to .env " "and fill it in.",
            file=sys.stderr,
        )
        return 2

    try:
        api_key, app_id, webhook_url = read_config()
        state = load_state()
        app_name = steam_app_name(
            app_id,
            state,
        )

        print(f"App: {app_name} ({app_id})")

        update_cache(
            api_key,
            app_id,
            state,
        )

        update_discord(
            webhook_url,
            state,
            app_id,
            app_name,
        )

        save_state(state)
        return 0

    except (
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
