"""Megan public-data discovery CLI: new Ethereum pools and transparent risk reports."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from public_sources import (
    SourceError,
    dexscreener_token_pairs,
    extract_pool_metrics,
    geckoterminal_new_pools,
    honeypot_check,
)
from risk_engine import RiskEvidence, assess

LOG = logging.getLogger("megan.research")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS candidates(
            token_address TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            pool_address TEXT, pool_created_at TEXT, pool_name TEXT, liquidity_usd REAL,
            market_json TEXT NOT NULL, risk_json TEXT NOT NULL, source_json TEXT NOT NULL)"""
        )
        self.db.commit()

    def upsert(self, token: str, pool: dict[str, Any], market: dict[str, Any], report: dict[str, Any]):
        self.db.execute(
            """INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(token_address) DO UPDATE SET last_seen=excluded.last_seen,
            pool_address=excluded.pool_address,pool_created_at=excluded.pool_created_at,
            pool_name=excluded.pool_name,liquidity_usd=excluded.liquidity_usd,
            market_json=excluded.market_json,risk_json=excluded.risk_json,source_json=excluded.source_json""",
            (
                token, now(), now(), pool.get("pool_address"), pool.get("created_at"),
                pool.get("pool_name"), _float(pool.get("reserve_usd")),
                json.dumps(market), json.dumps(report), json.dumps(pool),
            ),
        )
        self.db.commit()

    def close(self):
        self.db.close()


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


_COMMON_QUOTE_TOKENS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
}


def _token_address(pool: dict[str, Any]) -> str | None:
    """Choose a non-major-quote asset from a GeckoTerminal pool; ambiguous pairs stay unknown."""
    candidates: list[str] = []
    for key in ("base_token_id", "quote_token_id"):
        token_id = pool.get(key)
        if not isinstance(token_id, str) or "_" not in token_id:
            continue
        address = token_id.rsplit("_", 1)[-1]
        if len(address) == 42 and address.startswith("0x"):
            address = address.lower()
            if address not in candidates:
                candidates.append(address)
    non_quote = [address for address in candidates if address not in _COMMON_QUOTE_TOKENS]
    if len(non_quote) == 1:
        return non_quote[0]
    if len(candidates) == 1 and candidates[0] not in _COMMON_QUOTE_TOKENS:
        return candidates[0]
    return None


def scan_once(db: ResearchDB) -> int:
    pools = geckoterminal_new_pools()
    count = 0
    for pool in pools:
        address = _token_address(pool)
        if not address:
            continue

        market_pairs: list[dict[str, Any]] = []
        try:
            market_pairs = dexscreener_token_pairs(address)
        except SourceError as exc:
            LOG.warning("DEXScreener unavailable for %s: %s", address, exc)

        # Never substitute another pool for the exact pool discovered by GeckoTerminal.
        # A token may have many pools with different liquidity, taxes and risk profiles.
        discovered_pool = (pool.get("pool_address") or "").lower()
        matching_pairs = [
            pair for pair in market_pairs
            if isinstance(pair.get("pairAddress"), str)
            and pair["pairAddress"].lower() == discovered_pool
        ] if discovered_pool else []
        metrics = extract_pool_metrics(matching_pairs[0]) if matching_pairs else {}
        if market_pairs and not matching_pairs:
            LOG.warning(
                "No exact DEXScreener pair match for token %s / pool %s; "
                "leaving pool-specific market metrics unknown",
                address, discovered_pool or "(missing address)"
            )
        evidence = RiskEvidence(
            liquidity_usd=metrics.get("liquidity_usd") or _float(pool.get("reserve_usd")),
            liquidity_lock_status="unknown",
            notes=[
                "New pool discovered from GeckoTerminal public API",
                "Liquidity lock and holder concentration are not independently verified",
                "DEX transaction counts are not unique-wallet counts",
            ],
        )

        # Preserve UNKNOWN unless the provider response explicitly reports a boolean result.
        try:
            hp = honeypot_check(address)
            result = hp.get("honeypotResult") or {}
            explicit_honeypot = result.get("isHoneypot")
            if isinstance(explicit_honeypot, bool):
                evidence.honeypot = explicit_honeypot

            simulation = hp.get("simulationResult") or {}
            # A tax value being present does NOT prove that a buy/sell simulation succeeded.
            evidence.buy_tax_pct = _float(simulation.get("buyTax"))
            evidence.sell_tax_pct = _float(simulation.get("sellTax"))
            evidence.notes.append(
                "Provider response recorded; simulation success remains UNKNOWN unless an explicit success field is validated"
            )
        except (SourceError, ValueError) as exc:
            evidence.notes.append("Honeypot check unavailable: " + str(exc))

        report = assess(evidence)
        db.upsert(address, pool, metrics, report.__dict__)
        print(json.dumps({
            "token": address,
            "pool": pool.get("pool_address"),
            "metrics": metrics,
            "risk": report.__dict__,
        }, ensure_ascii=False))
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Megan public Ethereum token research watcher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/megan.sqlite3"))
    args = parser.parse_args()
    if args.interval < 5:
        parser.error("--interval must be at least 5 seconds")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = ResearchDB(args.db)
    try:
        while True:
            try:
                LOG.info("Scanned %s new-pool candidates", scan_once(db))
            except SourceError:
                LOG.exception("Primary new-pool source unavailable")
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        db.close()


if __name__ == "__main__":
    main()
