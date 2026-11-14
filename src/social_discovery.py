"""Read-only social discovery for newly observed Ethereum tokens.

Provider-listed links are evidence, not proof of official ownership. Telegram's
Bot API does not provide global public-group search by contract address.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

LOG = logging.getLogger("megan.socials")
UA = "Megan-Ethereum-Research/0.2 (+read-only)"


class SocialSourceError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request_headers = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise SocialSourceError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise SocialSourceError(f"Social source request failed: {exc}") from exc


def fetch_dexscreener_latest_profiles() -> list[dict[str, Any]]:
    """Merge new and recently updated profiles so delayed social links are not missed."""
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    successes = 0
    errors = []
    for endpoint in ("latest", "recent-updates"):
        try:
            payload = _get_json(f"https://api.dexscreener.com/token-profiles/{endpoint}/v1")
            successes += 1
            if isinstance(payload, list):
                for row in payload:
                    if not isinstance(row, dict):
                        continue
                    key = (str(row.get("chainId", "")).lower(),
                           str(row.get("tokenAddress", "")).lower())
                    if key[1]:
                        combined[key] = row
        except SocialSourceError as exc:
            errors.append(str(exc))
    if successes == 0:
        raise SocialSourceError("; ".join(errors) or "DEX Screener profile feeds unavailable")
    return list(combined.values())


def fetch_dextools_token(address: str, api_key: str) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("DEXTOOLS_API_KEY is empty")
    url = "https://public-api.dextools.io/v3/tokens/ether/" + urllib.parse.quote(address)
    payload = _get_json(url, {"X-API-Key": api_key.strip()})
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def fetch_x_recent_posts(address: str, bearer_token: str) -> list[dict[str, Any]]:
    if not bearer_token.strip():
        raise ValueError("X_BEARER_TOKEN is empty")
    params = urllib.parse.urlencode({
        "query": f'"{address}" -is:retweet',
        "max_results": "10",
        "tweet.fields": "created_at,public_metrics,author_id",
    })
    payload = _get_json(
        "https://api.x.com/2/tweets/search/recent?" + params,
        {"Authorization": "Bearer " + bearer_token.strip()},
    )
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _platform(platform: Any, url: str) -> str | None:
    name = str(platform or "").strip().lower()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if name in {"x", "twitter"} or host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return "x"
    if name in {"telegram", "tg"} or host in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        return "telegram"
    if name == "discord" or host.endswith(("discord.gg", "discord.com")):
        return "discord"
    if name in {"website", "web", "site"}:
        return "website"
    return name or None


def _append_link(links: list[dict[str, Any]], seen: set[tuple[str, str]],
                 platform: Any, url: Any, source: str) -> None:
    if not isinstance(url, str):
        return
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return
    kind = _platform(platform, url)
    if not kind:
        return
    key = (kind, url.rstrip("/"))
    if key in seen:
        return
    seen.add(key)
    links.append({
        "platform": kind, "url": url, "source": source,
        "evidence": "listed_by_provider", "official_verified": False,
    })


def collect_social_evidence(address: str,
                            dexscreener_profiles: list[dict[str, Any]] | None = None,
                            dextools_token: dict[str, Any] | None = None,
                            x_posts: list[dict[str, Any]] | None = None,
                            telegram_groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(address, str) or len(address) != 42 or not address.lower().startswith("0x"):
        raise ValueError("Expected a 20-byte Ethereum token address")
    target = address.lower()
    profiles = [
        row for row in (dexscreener_profiles or [])
        if isinstance(row, dict)
        and str(row.get("chainId", "")).lower() in {"ethereum", "eth"}
        and str(row.get("tokenAddress", "")).lower() == target
    ]
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for profile in profiles:
        for item in profile.get("links") or []:
            if isinstance(item, dict):
                _append_link(links, seen, item.get("type") or item.get("label"),
                             item.get("url"), "dexscreener")
    if isinstance(dextools_token, dict):
        socials = dextools_token.get("socialInfo") or dextools_token.get("social_info") or {}
        if isinstance(socials, dict):
            for platform, url in socials.items():
                _append_link(links, seen, platform, url, "dextools")

    mentions = []
    if x_posts is not None:
        for post in x_posts:
            if not isinstance(post, dict):
                continue
            body = str(post.get("text") or "")
            if target not in body.lower():
                continue
            post_id = str(post.get("id") or "")
            mentions.append({
                "post_id": post_id, "text": body[:2000],
                "created_at": post.get("created_at"),
                "author_id": post.get("author_id"),
                "public_metrics": post.get("public_metrics"),
                "url": f"https://x.com/i/web/status/{post_id}" if post_id.isdigit() else None,
                "source": "x_recent_search",
                "evidence": "exact_contract_address_mention",
                "official_verified": False,
            })
    has_telegram = any(row["platform"] == "telegram" for row in links)
    return {
        "token_address": target,
        "checked_at": _iso(_now()),
        "provider_profile_matches": len(profiles),
        "links": links,
        "x_mentions": mentions,
        "telegram_groups": telegram_groups or [],
        "x_search_url": "https://x.com/search?q=" + urllib.parse.quote(f'"{address}"'),
        "telegram_status": ("group_found_by_account_search" if telegram_groups else
                            "searched_no_group_match" if telegram_groups is not None else
                            "provider_link_found" if has_telegram else "no_provider_link_found"),
        "x_status": "exact_mentions_found" if mentions else (
            "searched_no_exact_mentions" if x_posts is not None else "search_url_only"),
        "overall_status": "evidence_found" if links or mentions or telegram_groups else "no_public_evidence_found",
        "important_note": "Provider-listed links and posts are not proof of official ownership or legitimacy.",
    }



async def _telegram_search_async(address: str, api_id: int, api_hash: str,
                                 session_file: str, limit: int) -> list[dict[str, Any]]:
    try:
        from telethon import TelegramClient, functions, types
    except ImportError as exc:
        raise SocialSourceError("Install optional Telegram support: pip install -e '.[telegram]'") from exc
    client = TelegramClient(session_file, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SocialSourceError("Telegram session is not authorized; run megan-telegram-login locally")
        result = await client(functions.messages.SearchGlobalRequest(
            q=address,
            filter=types.InputMessagesFilterEmpty(),
            min_date=None,
            max_date=None,
            offset_rate=0,
            offset_peer=types.InputPeerEmpty(),
            offset_id=0,
            limit=limit,
            groups_only=True,
        ))
        chats = {int(chat.id): chat for chat in (getattr(result, "chats", None) or [])}
        found: dict[int, dict[str, Any]] = {}
        for message in (getattr(result, "messages", None) or []):
            body = str(getattr(message, "message", None) or "")
            if address.lower() not in body.lower():
                continue
            peer = getattr(message, "peer_id", None)
            peer_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
            if peer_id is None:
                continue
            chat = chats.get(int(peer_id))
            if chat is None or bool(getattr(chat, "broadcast", False)):
                continue
            chat_id = int(chat.id)
            username = getattr(chat, "username", None)
            found.setdefault(chat_id, {
                "chat_id": str(chat_id),
                "title": getattr(chat, "title", None),
                "username": username,
                "url": f"https://t.me/{username}" if username else None,
                "message_id": int(getattr(message, "id", 0)),
                "message_date": getattr(message, "date", None).isoformat()
                    if getattr(message, "date", None) else None,
                "message_excerpt": body[:1000],
                "source": "telegram_mtproto_groups_only",
                "evidence": "exact_contract_address_mention",
                "official_verified": False,
                "public_username": bool(username),
            })
        return list(found.values())
    finally:
        await client.disconnect()


def search_telegram_groups(address: str, api_id: int, api_hash: str,
                           session_file: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search groups using the user's local MTProto session, never a bot token."""
    import asyncio
    if api_id <= 0 or not api_hash or not session_file:
        raise ValueError("Telegram API ID, API hash and session file are required")
    return asyncio.run(_telegram_search_async(address, api_id, api_hash, session_file, limit))


class SocialStore:
    def __init__(self, path: str):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        tables = {r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "tokens" not in tables:
            raise RuntimeError("Megan tokens table not found; start megan-watch first")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS social_evidence (
              token_address TEXT PRIMARY KEY, first_checked_at TEXT NOT NULL,
              last_checked_at TEXT NOT NULL, next_check_at TEXT NOT NULL,
              status TEXT NOT NULL, evidence_json TEXT NOT NULL
            )
        """)
        self.db.commit()

    def due_tokens(self, limit: int):
        return self.db.execute("""
            SELECT t.address,t.observed_at FROM tokens t
            LEFT JOIN social_evidence s ON lower(s.token_address)=lower(t.address)
            WHERE s.next_check_at IS NULL OR s.next_check_at <= ?
            ORDER BY t.block_number DESC LIMIT ?
        """, (_iso(_now()), limit)).fetchall()

    def save(self, address: str, observed_at: str, evidence: dict[str, Any]) -> None:
        try:
            launch_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            age = max(0, (_now() - launch_time).total_seconds())
        except (TypeError, ValueError):
            age = 3600
        delay = 30 if age < 300 else (300 if age < 86400 else 3600)
        checked = _iso(_now())
        self.db.execute("""
            INSERT INTO social_evidence VALUES(?,?,?,?,?,?)
            ON CONFLICT(token_address) DO UPDATE SET
              last_checked_at=excluded.last_checked_at,
              next_check_at=excluded.next_check_at,
              status=excluded.status,evidence_json=excluded.evidence_json
        """, (address.lower(), checked, checked,
              _iso(_now() + timedelta(seconds=delay)),
              evidence["overall_status"], json.dumps(evidence, ensure_ascii=False)))
        self.db.commit()

    def close(self):
        self.db.close()


def scan_once(database_path: str, limit: int = 20) -> int:
    store = SocialStore(database_path)
    try:
        due = store.due_tokens(limit)
        if not due:
            LOG.info("No tokens are due for social re-check")
            return 0
        try:
            profiles = fetch_dexscreener_latest_profiles()
        except SocialSourceError as exc:
            LOG.warning("DEX Screener profile feed unavailable: %s", exc)
            profiles = []
        dt_key = os.getenv("DEXTOOLS_API_KEY", "").strip()
        x_token = os.getenv("X_BEARER_TOKEN", "").strip()
        tg_api_id = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
        tg_api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        tg_session = os.getenv("TELEGRAM_SESSION_FILE", "data/telegram_user").strip()
        tg_session_exists = Path(tg_session + ".session").is_file()
        count = 0
        for row in due:
            address = str(row["address"])
            dt_data = None
            x_posts = None
            telegram_groups = None
            if dt_key:
                try:
                    dt_data = fetch_dextools_token(address, dt_key)
                except SocialSourceError as exc:
                    LOG.warning("DEXTools lookup failed for %s: %s", address, exc)
            if x_token:
                try:
                    x_posts = fetch_x_recent_posts(address, x_token)
                except SocialSourceError as exc:
                    LOG.warning("X search failed for %s: %s", address, exc)
            # Search Telegram for every due token. A cycle-level flag here silently
            # skipped all but the first token, leaving later reports without Telegram evidence.
            if tg_api_id > 0 and tg_api_hash and tg_session_exists:
                try:
                    telegram_groups = search_telegram_groups(address, tg_api_id, tg_api_hash, tg_session)
                except Exception as exc:
                    LOG.warning("Telegram group search failed for %s: %s", address, exc)
            evidence = collect_social_evidence(address, profiles, dt_data, x_posts, telegram_groups)
            store.save(address, str(row["observed_at"]), evidence)
            print(json.dumps(evidence, ensure_ascii=False))
            count += 1
        return count
    finally:
        store.close()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Megan read-only Telegram/X link discovery")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/megan.sqlite3"))
    args = parser.parse_args()
    if args.interval < 5 or args.limit < 1:
        parser.error("--interval must be >= 5 and --limit must be >= 1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            scan_once(args.db, args.limit)
        except Exception:
            LOG.exception("Social scan failed")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
