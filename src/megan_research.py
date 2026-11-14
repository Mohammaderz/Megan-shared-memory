"""Megan public-data discovery CLI: new Ethereum pools and transparent risk reports."""
from __future__ import annotations
import argparse, json, logging, os, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from public_sources import geckoterminal_new_pools, dexscreener_token_pairs, honeypot_check, extract_pool_metrics, SourceError
from risk_engine import RiskEvidence, assess

LOG = logging.getLogger("megan.research")
def now(): return datetime.now(timezone.utc).isoformat()

class ResearchDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS candidates(
        token_address TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        pool_address TEXT, pool_created_at TEXT, pool_name TEXT, liquidity_usd REAL,
        market_json TEXT NOT NULL, risk_json TEXT NOT NULL, source_json TEXT NOT NULL)""")
        self.db.commit()
    def upsert(self, token: str, pool: dict[str,Any], market: dict[str,Any], report: dict[str,Any]):
        self.db.execute("""INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(token_address) DO UPDATE SET last_seen=excluded.last_seen,
        pool_address=excluded.pool_address,pool_created_at=excluded.pool_created_at,
        pool_name=excluded.pool_name,liquidity_usd=excluded.liquidity_usd,
        market_json=excluded.market_json,risk_json=excluded.risk_json,source_json=excluded.source_json""",
        (token,now(),now(),pool.get("pool_address"),pool.get("created_at"),pool.get("pool_name"),
         _float(pool.get("reserve_usd")),json.dumps(market),json.dumps(report),json.dumps(pool)))
        self.db.commit()
    def close(self): self.db.close()

def _float(v):
    try:return float(v) if v is not None else None
    except (TypeError,ValueError):return None

def scan_once(db: ResearchDB) -> int:
    pools=geckoterminal_new_pools()
    count=0
    for pool in pools:
        token_id=pool.get("base_token_id") or ""
        address=token_id.split("_")[-1] if "_" in token_id else ""
        if len(address)!=42 or not address.startswith("0x"): continue
        market_pairs=[]
        try: market_pairs=dexscreener_token_pairs(address)
        except SourceError as exc: LOG.warning("DEXScreener unavailable for %s: %s",address,exc)
        metrics=extract_pool_metrics(max(market_pairs,key=lambda p:_float((p.get("liquidity") or {}).get("usd")) or 0)) if market_pairs else {}
        evidence=RiskEvidence(
            liquidity_usd=metrics.get("liquidity_usd") or _float(pool.get("reserve_usd")),
            unique_buyers_1h=None, unique_sellers_1h=None,
            liquidity_lock_status="unknown",
            notes=["New pool discovered from GeckoTerminal public API",
                   "Liquidity lock and holder concentration are not yet independently verified",
                   "DEX volume/transaction counts are not unique-wallet counts"]
        )
        # Honeypot endpoint is attempted, but absence/failure remains UNKNOWN.
        try:
            hp=honeypot_check(address)
            result=hp.get("honeypotResult") or {}
            evidence.honeypot=result.get("isHoneypot") if isinstance(result.get("isHoneypot"),bool) else None
            simulation=hp.get("simulationResult") or {}
            evidence.simulation_buy_ok=simulation.get("buyTax") is not None if simulation else None
            evidence.buy_tax_pct=_float(simulation.get("buyTax"))
            evidence.sell_tax_pct=_float(simulation.get("sellTax"))
            evidence.notes.append("Honeypot.is response captured; sell simulation fields require provider-schema validation")
        except (SourceError,ValueError) as exc:
            evidence.notes.append("Honeypot check unavailable: "+str(exc))
        report=assess(evidence)
        db.upsert(address,pool,metrics,report.__dict__)
        print(json.dumps({"token":address,"pool":pool.get("pool_address"),"metrics":metrics,
                          "risk":report.__dict__},ensure_ascii=False))
        count+=1
    return count

def main():
    parser=argparse.ArgumentParser(description="Megan public Ethereum token research watcher")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=30)
    parser.add_argument("--db",default=os.getenv("DATABASE_PATH","data/megan.sqlite3"))
    args=parser.parse_args()
    if args.interval<5: parser.error("--interval must be at least 5 seconds")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    db=ResearchDB(args.db)
    try:
        while True:
            try: LOG.info("Scanned %s new-pool candidates",scan_once(db))
            except SourceError: LOG.exception("Primary new-pool source unavailable")
            if args.once: break
            time.sleep(args.interval)
    finally: db.close()
if __name__=="__main__": main()
