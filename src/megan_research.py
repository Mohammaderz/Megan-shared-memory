"""Ethereum token research: source-alert handoff, market context, and risk report."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from public_sources import (
    SourceError, dexscreener_token_pairs, extract_pool_metrics,
    geckoterminal_new_pools, honeypot_check,
)
from risk_engine import RiskEvidence, assess

LOG = logging.getLogger("megan.research")
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS candidates(
                token_address TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                pool_address TEXT, pool_created_at TEXT, pool_name TEXT, liquidity_usd REAL,
                market_json TEXT NOT NULL, risk_json TEXT NOT NULL, source_json TEXT NOT NULL
            )
        """)
        self.db.commit()

    def upsert(self, token: str, pool: dict[str, Any], market: dict[str, Any],
               report: dict[str, Any]) -> None:
        self.db.execute("""
            INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(token_address) DO UPDATE SET last_seen=excluded.last_seen,
            pool_address=excluded.pool_address,pool_created_at=excluded.pool_created_at,
            pool_name=excluded.pool_name,liquidity_usd=excluded.liquidity_usd,
            market_json=excluded.market_json,risk_json=excluded.risk_json,
            source_json=excluded.source_json
        """, (token, now(), now(), pool.get("pool_address"), pool.get("created_at"),
              pool.get("pool_name"), _float(pool.get("reserve_usd")),
              json.dumps(market), json.dumps(report), json.dumps(pool)))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def analyze_token_address(db: ResearchDB, address: str,
                          source_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze an address immediately after an alert, even before a DEX pool exists."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        raise ValueError("Expected a 20-byte Ethereum contract address")
    address = address.lower()
    context = dict(source_context or {})
    pool = {
        "source": context.get("source", "direct_address"),
        "source_name": context.get("source_name"),
        "source_url": context.get("source_url"),
        "source_external_id": context.get("source_external_id"),
        "pool_address": context.get("pool_address"),
        "created_at": context.get("created_at"),
        "pool_name": context.get("pool_name"),
        "reserve_usd": context.get("reserve_usd"),
    }

    pairs: list[dict[str, Any]] = []
    try:
        pairs = dexscreener_token_pairs(address)
    except SourceError as exc:
        LOG.warning("DEX Screener unavailable for %s: %s", address, exc)

    # Prefer the exact pool that generated the alert; otherwise use the most liquid
    # Ethereum pair returned for this token, not an unrelated chain's pair.
    preferred = str(pool.get("pool_address") or "").lower()
    selected = next((p for p in pairs
                     if preferred and str(p.get("pairAddress") or "").lower() == preferred), None)
    if selected is None and pairs:
        selected = max(pairs, key=lambda p: _float((p.get("liquidity") or {}).get("usd")) or 0)
    metrics = extract_pool_metrics(selected) if selected else {}
    if selected:
        pool["pool_address"] = selected.get("pairAddress") or pool.get("pool_address")
        pool["pool_name"] = selected.get("baseToken", {}).get("name") or pool.get("pool_name")
        pool["reserve_usd"] = (selected.get("liquidity") or {}).get("usd") or pool.get("reserve_usd")

    evidence = RiskEvidence(
        liquidity_usd=metrics.get("liquidity_usd") or _float(pool.get("reserve_usd")),
        liquidity_lock_status="unknown",
        notes=[
            "Token address received from an immediate source alert or new-pool feed",
            "DEX transaction counts are not unique-wallet counts",
            "Holder concentration, LP lock, deployer history, and contract privileges remain UNKNOWN unless independently sourced",
        ],
    )
    try:
        hp = honeypot_check(address)
        hp_result = hp.get("honeypotResult") or {}
        is_honeypot = hp_result.get("isHoneypot")
        evidence.honeypot = is_honeypot if isinstance(is_honeypot, bool) else None
        simulation = hp.get("simulationResult") or {}
        evidence.buy_tax_pct = _float(simulation.get("buyTax"))
        evidence.sell_tax_pct = _float(simulation.get("sellTax"))
        simulation_success = hp.get("simulationSuccess")
        if isinstance(simulation_success, bool) and simulation_success:
            evidence.simulation_buy_ok = True
            evidence.simulation_sell_ok = True
        elif hp.get("simulationError"):
            evidence.notes.append("Honeypot.is simulation did not complete: " + str(hp["simulationError"])[:500])
        evidence.notes.append("Simulation success is read from the API-level simulationSuccess field; tax presence is not treated as a successful simulation")
    except (SourceError, ValueError) as exc:
        evidence.notes.append("Honeypot check unavailable: " + str(exc))

    report = assess(evidence)
    db.upsert(address, pool, metrics, report.__dict__)
    result = {
        "token": address,
        "pool": pool.get("pool_address"),
        "source": context,
        "metrics": metrics,
        "risk": report.__dict__,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def scan_once(db: ResearchDB) -> int:
    pools = geckoterminal_new_pools()
    count = 0
    for pool in pools:
        token_id = pool.get("base_token_id") or ""
        address = token_id.split("_")[-1] if "_" in token_id else ""
        if not ADDRESS_RE.fullmatch(address):
            LOG.warning("Skipping malformed GeckoTerminal base token id: %r", token_id)
            continue
        analyze_token_address(db, address, {
            "source": "geckoterminal_new_pool",
            "source_name": pool.get("pool_name"),
            "pool_address": pool.get("pool_address"),
            "created_at": pool.get("created_at"),
            "pool_name": pool.get("pool_name"),
            "reserve_usd": pool.get("reserve_usd"),
        })
        count += 1
    return count


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Megan public Ethereum token research watcher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    if args.db is None:
        args.db = os.getenv("DATABASE_PATH", "data/megan.sqlite3")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
