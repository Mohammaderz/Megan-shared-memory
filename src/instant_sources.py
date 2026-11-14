"""Fast intake for Ethereum contract addresses published by configured RSS sites and Telegram channels.

This module only ingests public alerts. It does not sign, buy, sell, or execute transactions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

LOG = logging.getLogger("megan.sources")
ADDRESS_RE = re.compile(r"(?<![0-9a-fA-F])0x[a-fA-F0-9]{40}(?![0-9a-fA-F])")
USER_AGENT = "Megan-Ethereum-Source-Intake/0.2"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ethereum_addresses(text: str) -> list[str]:
    """Return unique, lower-case 20-byte EVM addresses in first-seen order."""
    found: list[str] = []
    seen: set[str] = set()
    for match in ADDRESS_RE.findall(text or ""):
        address = match.lower()
        if address not in seen:
            seen.add(address)
            found.append(address)
    return found


def split_sources(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


@dataclass(frozen=True)
class SourceAlert:
    source_type: str
    source_name: str
    external_id: str
    published_at: str | None
    url: str | None
    text: str
    addresses: tuple[str, ...]


class AlertStore:
    """Durable deduplication; each source message is processed once."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS source_alerts (
                fingerprint TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                external_id TEXT NOT NULL,
                published_at TEXT,
                url TEXT,
                body TEXT NOT NULL,
                addresses_json TEXT NOT NULL,
                first_seen TEXT NOT NULL
            )
        """)
        self.db.commit()

    def add(self, alert: SourceAlert) -> bool:
        fingerprint = hashlib.sha256(
            f"{alert.source_type}|{alert.source_name}|{alert.external_id}".encode()
        ).hexdigest()
        cur = self.db.execute("""
            INSERT OR IGNORE INTO source_alerts
            (fingerprint,source_type,source_name,external_id,published_at,url,body,addresses_json,first_seen)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (fingerprint, alert.source_type, alert.source_name, alert.external_id,
              alert.published_at, alert.url, alert.text,
              json.dumps(alert.addresses), utc_now()))
        self.db.commit()
        return cur.rowcount == 1

    def close(self) -> None:
        self.db.close()


def _http_get(url: str, timeout: int = 12) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} from {url}")
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"RSS fetch failed for {url}: {exc}") from exc


def fetch_rss(url: str) -> list[SourceAlert]:
    """Read RSS 2.0 or Atom feed entries using only the Python standard library."""
    root = ET.fromstring(_http_get(url))
    alerts: list[SourceAlert] = []
    for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        def value(names: Iterable[str]) -> str:
            for name in names:
                node = item.find(name)
                if node is not None and node.text:
                    return node.text.strip()
            return ""

        title = value(("title", "{http://www.w3.org/2005/Atom}title"))
        summary = value(("description", "summary", "{http://www.w3.org/2005/Atom}summary",
                         "{http://www.w3.org/2005/Atom}content"))
        link = value(("link",))
        if not link:
            link_node = item.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        external_id = value(("guid", "id", "{http://www.w3.org/2005/Atom}id")) or link or hashlib.sha256(
            (title + summary).encode()
        ).hexdigest()
        body = f"{title}\n{summary}"
        addresses = tuple(ethereum_addresses(body))
        if addresses:
            alerts.append(SourceAlert("rss", url, external_id,
                                      value(("pubDate", "published", "updated",
                                             "{http://www.w3.org/2005/Atom}published")),
                                      link or None, body, addresses))
    return alerts


def fetch_telegram(channel: str, limit: int = 50) -> list[SourceAlert]:
    """Fetch public channel messages via Telethon; requires a user-authorized session.

    Bot tokens cannot reliably read arbitrary public channels. The operator must
    create/authorize a local Telethon session and must respect Telegram terms.
    """
    try:
        from telethon.sync import TelegramClient
    except ImportError as exc:
        raise RuntimeError("Install Telegram support with: pip install -e '.[telegram]'") from exc

    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session = os.getenv("TELEGRAM_SESSION", "data/telegram_session").strip()
    if not api_id or not api_hash:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH; never commit these credentials")
    alerts: list[SourceAlert] = []
    with TelegramClient(session, int(api_id), api_hash) as client:
        entity = client.get_entity(channel)
        for message in client.get_messages(entity, limit=limit):
            body = message.message or ""
            addresses = tuple(ethereum_addresses(body))
            if not addresses:
                continue
            external_id = str(message.id)
            username = getattr(entity, "username", None)
            url = f"https://t.me/{username}/{message.id}" if username else None
            published = message.date.isoformat() if message.date else None
            alerts.append(SourceAlert("telegram", channel, external_id, published,
                                      url, body, addresses))
    return alerts


def poll_sources(store: AlertStore, rss_urls: list[str], channels: list[str]) -> list[dict]:
    """Poll configured sources; isolate per-source errors and return only fresh alerts."""
    fresh: list[dict] = []
    for source in rss_urls:
        try:
            alerts = fetch_rss(source)
        except Exception:
            LOG.exception("RSS source failed: %s", source)
            continue
        for alert in alerts:
            if store.add(alert):
                fresh.append(asdict(alert))
    for channel in channels:
        try:
            alerts = fetch_telegram(channel)
        except Exception:
            LOG.exception("Telegram source failed: %s", channel)
            continue
        for alert in alerts:
            if store.add(alert):
                fresh.append(asdict(alert))
    return fresh


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll configured Ethereum contract-alert sources")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=3)
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/megan.sqlite3"))
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be at least one second")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rss = split_sources(os.getenv("RSS_ALERT_FEEDS", ""))
    channels = split_sources(os.getenv("TELEGRAM_CHANNELS", ""))
    if not rss and not channels:
        parser.error("Configure RSS_ALERT_FEEDS and/or TELEGRAM_CHANNELS in .env")
    store = AlertStore(args.db)
    try:
        while True:
            alerts = poll_sources(store, rss, channels)
            # Hand fresh alert addresses straight to the research pipeline in this process.
            # A message may mention the same contract more than once; analyze it once per poll.
            if alerts:
                from megan_research import ResearchDB, analyze_token_address
                research_db = ResearchDB(args.db)
                analyzed: set[str] = set()
                try:
                    for alert in alerts:
                        for address in alert["addresses"]:
                            if address in analyzed:
                                continue
                            analyzed.add(address)
                            analyze_token_address(research_db, address, {
                                "source": alert["source_type"],
                                "source_name": alert["source_name"],
                                "source_url": alert.get("url"),
                                "source_external_id": alert["external_id"],
                                "published_at": alert.get("published_at"),
                            })
                finally:
                    research_db.close()
            for alert in alerts:
                print(json.dumps(alert, ensure_ascii=False))
            LOG.info("New contract-alert messages: %d; unique contract addresses: %d",
                     len(alerts), len({a for alert in alerts for a in alert["addresses"]}))
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
