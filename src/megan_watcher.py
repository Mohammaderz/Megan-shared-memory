"""Megan Ethereum watcher: discover newly deployed ERC-20-like contracts and DEX pools.

This is an observation-only MVP. It never signs or sends transactions.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import ContractLogicError

from trace_discovery import ContractCreation, TraceDiscovery

LOG = logging.getLogger("megan")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SELECTORS = {
    "name": "0x06fdde03",
    "symbol": "0x95d89b41",
    "decimals": "0x313ce567",
    "total_supply": "0x18160ddd",
    "owner": "0x8da5cb5b",
}
V2_EVENT = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()
V3_EVENT = Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_addresses(key: str) -> list[str]:
    raw = os.getenv(key, "")
    values = [part.strip() for part in raw.split(",") if part.strip()]
    result = []
    for value in values:
        if not Web3.is_address(value):
            raise ValueError(f"Invalid address in {key}: {value}")
        result.append(Web3.to_checksum_address(value))
    return result


def decode_text(data: bytes) -> str | None:
    """Decode ABI string, falling back to bytes32 for legacy ERC-20 metadata."""
    if not data:
        return None
    try:
        offset = int.from_bytes(data[:32], "big")
        if offset + 32 <= len(data):
            size = int.from_bytes(data[offset:offset + 32], "big")
            raw = data[offset + 32:offset + 32 + size]
            if offset + 32 + size <= len(data) and raw:
                return raw.decode("utf-8", errors="replace").rstrip("\x00")
    except (ValueError, UnicodeDecodeError):
        pass
    try:
        return data[:32].split(b"\x00", 1)[0].decode("utf-8", errors="replace") or None
    except UnicodeDecodeError:
        return None


def decode_uint(data: bytes) -> int | None:
    return int.from_bytes(data[-32:], "big") if len(data) >= 32 else None


def _topic_address(topic: bytes) -> str:
    raw = bytes(topic)
    if len(raw) != 32 or raw[:12] != b"\x00" * 12:
        raise ValueError("Malformed indexed address topic")
    return Web3.to_checksum_address("0x" + raw[-20:].hex())


def _data_address(data: bytes, word_index: int) -> str:
    start = word_index * 32
    word = data[start:start + 32]
    if len(word) != 32 or word[:12] != b"\x00" * 12:
        raise ValueError("Malformed ABI address word")
    return Web3.to_checksum_address("0x" + word[-20:].hex())


def decode_v2_pair_created(topics: list[Any], data: bytes) -> tuple[str, str, str]:
    """Decode Uniswap-V2 PairCreated topics/data into token0, token1, pair."""
    if len(topics) != 3 or bytes(topics[0]) != bytes.fromhex(V2_EVENT[2:]):
        raise ValueError("Not a valid V2 PairCreated event")
    raw = bytes(data)
    if len(raw) != 64:
        raise ValueError("V2 PairCreated data must contain address and uint256 words")
    token0 = _topic_address(topics[1])
    token1 = _topic_address(topics[2])
    pair = _data_address(raw, 0)
    return token0, token1, pair


def decode_v3_pool_created(topics: list[Any], data: bytes) -> tuple[str, str, str, int]:
    """Decode Uniswap-V3 PoolCreated topics/data into token0, token1, pool, fee."""
    if len(topics) != 4 or bytes(topics[0]) != bytes.fromhex(V3_EVENT[2:]):
        raise ValueError("Not a valid V3 PoolCreated event")
    fee_word = bytes(topics[3])
    if len(fee_word) != 32 or int.from_bytes(fee_word[:29], "big") != 0:
        raise ValueError("Malformed V3 fee topic")
    fee = int.from_bytes(fee_word[-3:], "big")
    raw = bytes(data)
    if len(raw) != 64:
        raise ValueError("V3 PoolCreated data must contain int24 and address words")
    tick_word = raw[:32]
    tick_value = int.from_bytes(tick_word, "big", signed=True)
    if not -(2**23) <= tick_value < 2**23:
        raise ValueError("V3 tickSpacing is outside int24 range")
    token0 = _topic_address(topics[1])
    token1 = _topic_address(topics[2])
    pool = _data_address(raw, 1)
    return token0, token1, pool, fee


@dataclass
class TokenRecord:
    address: str
    creator: str | None
    creation_tx: str
    block_number: int
    block_hash: str
    observed_at: str
    name: str | None
    symbol: str | None
    decimals: int | None
    total_supply_raw: str | None
    owner: str | None
    bytecode_bytes: int
    metadata_complete: bool


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tokens (
          address TEXT PRIMARY KEY, creator TEXT, creation_tx TEXT NOT NULL,
          block_number INTEGER NOT NULL, block_hash TEXT NOT NULL, observed_at TEXT NOT NULL,
          name TEXT, symbol TEXT, decimals INTEGER, total_supply_raw TEXT, owner TEXT,
          bytecode_bytes INTEGER NOT NULL, metadata_complete INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pools (
          address TEXT PRIMARY KEY, dex_type TEXT NOT NULL, factory TEXT NOT NULL,
          token0 TEXT NOT NULL, token1 TEXT NOT NULL, fee TEXT, block_number INTEGER NOT NULL,
          tx_hash TEXT NOT NULL, observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deployments (
          address TEXT PRIMARY KEY, creator TEXT NOT NULL, tx_hash TEXT NOT NULL,
          block_number INTEGER NOT NULL, block_hash TEXT NOT NULL,
          creation_method TEXT NOT NULL, trace_provider TEXT NOT NULL, observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS block_coverage (
          block_number INTEGER PRIMARY KEY, block_hash TEXT NOT NULL,
          trace_status TEXT NOT NULL, trace_provider TEXT, trace_error TEXT, observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raw_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, block_number INTEGER NOT NULL,
          block_hash TEXT NOT NULL, tx_hash TEXT NOT NULL, log_index INTEGER,
          event_type TEXT NOT NULL, payload_json TEXT NOT NULL, observed_at TEXT NOT NULL,
          UNIQUE(block_hash, tx_hash, log_index, event_type)
        );
        """)
        self.db.commit()

    def get_state(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def add_token(self, token: TokenRecord) -> bool:
        values = asdict(token)
        values["metadata_complete"] = int(values["metadata_complete"])
        cur = self.db.execute("""
          INSERT OR IGNORE INTO tokens(address,creator,creation_tx,block_number,block_hash,observed_at,
          name,symbol,decimals,total_supply_raw,owner,bytecode_bytes,metadata_complete)
          VALUES(:address,:creator,:creation_tx,:block_number,:block_hash,:observed_at,
          :name,:symbol,:decimals,:total_supply_raw,:owner,:bytecode_bytes,:metadata_complete)
        """, values)
        self.db.commit()
        return cur.rowcount == 1

    def add_deployment(self, creation: ContractCreation, block_number: int, block_hash: str) -> bool:
        cur = self.db.execute("""
          INSERT OR IGNORE INTO deployments(address,creator,tx_hash,block_number,block_hash,
          creation_method,trace_provider,observed_at) VALUES(?,?,?,?,?,?,?,?)
        """, (creation.address, creation.creator, creation.tx_hash, block_number, block_hash,
              creation.creation_method, creation.provider, utc_now()))
        self.db.commit()
        return cur.rowcount == 1

    def set_trace_coverage(self, block_number: int, block_hash: str, status: str,
                           provider: str | None, error: str | None) -> None:
        self.db.execute("""
          INSERT INTO block_coverage(block_number,block_hash,trace_status,trace_provider,trace_error,observed_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(block_number) DO UPDATE SET
          block_hash=excluded.block_hash, trace_status=excluded.trace_status,
          trace_provider=excluded.trace_provider, trace_error=excluded.trace_error,
          observed_at=excluded.observed_at
        """, (block_number, block_hash, status, provider, error, utc_now()))
        self.db.commit()

    def add_pool(self, pool: dict[str, Any]) -> bool:
        cur = self.db.execute("""
          INSERT OR IGNORE INTO pools(address,dex_type,factory,token0,token1,fee,block_number,tx_hash,observed_at)
          VALUES(:address,:dex_type,:factory,:token0,:token1,:fee,:block_number,:tx_hash,:observed_at)
        """, pool)
        self.db.commit()
        return cur.rowcount == 1

    def add_event(self, block: int, block_hash: str, tx_hash: str, log_index: int | None,
                  event_type: str, payload: dict[str, Any], observed_at: str) -> None:
        self.db.execute("""
          INSERT OR IGNORE INTO raw_events(block_number,block_hash,tx_hash,log_index,event_type,payload_json,observed_at)
          VALUES(?,?,?,?,?,?,?)
        """, (block, block_hash, tx_hash, log_index, event_type, json.dumps(payload, ensure_ascii=False), observed_at))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class EthereumWatcher:
    def __init__(self, rpc_url: str, db_path: str, poll_seconds: float,
                 confirmations: int, start_block: int | None,
                 v2_factories: list[str], v3_factories: list[str],
                 trace_mode: str = "auto", trace_required: bool = False):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 25}))
        if not self.w3.is_connected():
            raise ConnectionError("RPC endpoint is not reachable")
        self.chain_id = self.w3.eth.chain_id
        if self.chain_id != 1:
            raise ValueError(f"Expected Ethereum mainnet chain_id=1, got {self.chain_id}")
        if trace_required and trace_mode.strip().lower() == "off":
            raise ValueError("TRACE_REQUIRED cannot be true when TRACE_MODE=off")
        self.store = Store(db_path)
        if poll_seconds <= 0:
            raise ValueError("POLL_SECONDS must be greater than zero")
        if confirmations < 0:
            raise ValueError("CONFIRMATIONS cannot be negative")
        if start_block is not None and start_block < 0:
            raise ValueError("START_BLOCK cannot be negative")
        self.poll_seconds = poll_seconds
        self.confirmations = confirmations
        self.start_block = start_block
        self.v2_factories = v2_factories
        self.v3_factories = v3_factories
        self.trace = TraceDiscovery(self.w3, trace_mode)
        self.trace_required = trace_required
        self.running = True

    def stop(self, *_: Any) -> None:
        self.running = False

    def call(self, address: str, selector: str, block: int) -> bytes:
        return bytes(self.w3.eth.call({"to": address, "data": selector}, block_identifier=block))

    def inspect_token(self, address: str, creator: str | None, tx_hash: str,
                      block_number: int, block_hash: str) -> TokenRecord | None:
        # Infrastructure failures here must escape to the block loop. Treating an
        # RPC outage as "not a token" would silently advance an incomplete scan.
        bytecode = bytes(self.w3.eth.get_code(address, block_identifier=block_number))
        if not bytecode:
            return None
        values: dict[str, Any] = {}
        for key in ("name", "symbol", "decimals", "total_supply", "owner"):
            try:
                raw = self.call(address, SELECTORS[key], block_number)
                if key in ("name", "symbol"):
                    values[key] = decode_text(raw)
                elif key == "owner":
                    values[key] = Web3.to_checksum_address("0x" + raw[-20:].hex()) if len(raw) >= 32 else None
                else:
                    values[key] = decode_uint(raw)
            except ContractLogicError:
                # A contract-level revert can mean this optional method is unavailable.
                # Provider/network failures must propagate so the block cursor cannot skip data.
                values[key] = None
        # ERC-20-like heuristic: at least two identity/quantity methods must respond.
        evidence_count = sum(values.get(k) is not None for k in ("name", "symbol", "decimals", "total_supply"))
        if evidence_count < 2:
            return None
        return TokenRecord(
            address=Web3.to_checksum_address(address), creator=creator, creation_tx=tx_hash,
            block_number=block_number, block_hash=block_hash, observed_at=utc_now(),
            name=values.get("name"), symbol=values.get("symbol"),
            decimals=values.get("decimals"), total_supply_raw=str(values["total_supply"]) if values.get("total_supply") is not None else None,
            owner=values.get("owner"), bytecode_bytes=len(bytecode),
            metadata_complete=all(values.get(k) is not None for k in ("name", "symbol", "decimals", "total_supply")),
        )

    def scan_deployments(self, block: Any) -> int:
        discovered = 0
        for tx in block["transactions"]:
            if tx.get("to") is not None:
                continue
            tx_hash = tx["hash"].hex()
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx["hash"])
                address = receipt.get("contractAddress")
                if int(receipt["status"]) != 1 or not address:
                    continue
                creation = ContractCreation(
                    Web3.to_checksum_address(address).lower(),
                    Web3.to_checksum_address(tx["from"]).lower(), tx_hash, "create", "eth_receipt",
                )
                self.store.add_deployment(creation, block["number"], block["hash"].hex())
                token = self.inspect_token(address, tx.get("from"), tx_hash, block["number"], block["hash"].hex())
                if token and self.store.add_token(token):
                    discovered += 1
                    LOG.info("NEW TOKEN %s (%s) at block %s", token.address, token.symbol or "?", block["number"])
                    self.store.add_event(block["number"], block["hash"].hex(), tx_hash, None,
                                         "token_discovered", asdict(token), utc_now())
            except Exception:
                LOG.exception("Could not inspect contract creation tx %s", tx_hash)
                raise
        return discovered

    def scan_traced_deployments(self, block_number: int, block_hash: str) -> int:
        if self.trace.mode == "off":
            self.store.set_trace_coverage(block_number, block_hash, "disabled", None, None)
            return 0
        try:
            batch = self.trace.trace_block(block_number)
        except Exception as exc:
            self.store.set_trace_coverage(block_number, block_hash, "unavailable", None, str(exc)[:2000])
            LOG.warning("TRACE COVERAGE UNAVAILABLE at block %s: %s", block_number, exc)
            if self.trace_required:
                raise
            return 0

        # Do not swallow failures while inspecting created contracts: these are
        # data-acquisition failures and must stop block advancement for a retry.
        added = 0
        for creation in batch.creations:
            address = Web3.to_checksum_address(creation.address)
            creator = Web3.to_checksum_address(creation.creator)
            normalized = ContractCreation(address.lower(), creator.lower(), creation.tx_hash,
                                          creation.creation_method, creation.provider)
            if self.store.add_deployment(normalized, block_number, block_hash):
                added += 1
            token = self.inspect_token(address, creator, creation.tx_hash, block_number, block_hash)
            if token and self.store.add_token(token):
                LOG.info("NEW TRACED TOKEN %s (%s) via %s at block %s",
                         token.address, token.symbol or "?", creation.creation_method, block_number)
                self.store.add_event(block_number, block_hash, creation.tx_hash, None,
                                     "token_discovered_trace", asdict(token), utc_now())
        self.store.set_trace_coverage(block_number, block_hash, "complete", batch.provider, None)
        return added

    def scan_factory_logs(self, block_number: int, block_hash: str) -> int:
        found = 0
        for dex_type, factories, topic in (
            ("uniswap_v2_style", self.v2_factories, V2_EVENT),
            ("uniswap_v3_style", self.v3_factories, V3_EVENT),
        ):
            for factory in factories:
                try:
                    logs = self.w3.eth.get_logs({
                        "fromBlock": block_number, "toBlock": block_number,
                        "address": factory, "topics": [topic],
                    })
                    for item in logs:
                        topics = item["topics"]
                        if dex_type == "uniswap_v2_style":
                            token0, token1, pool_address = decode_v2_pair_created(topics, bytes(item["data"]))
                            fee = None
                        else:
                            # V3 fee is indexed in topics[3]; data is int24 tickSpacing + pool address.
                            token0, token1, pool_address, fee_value = decode_v3_pool_created(topics, bytes(item["data"]))
                            fee = str(fee_value)
                        record = {
                            "address": pool_address, "dex_type": dex_type, "factory": factory,
                            "token0": token0, "token1": token1, "fee": fee,
                            "block_number": block_number, "tx_hash": item["transactionHash"].hex(),
                            "observed_at": utc_now(),
                        }
                        if self.store.add_pool(record):
                            found += 1
                            LOG.info("NEW POOL %s %s/%s at block %s", pool_address, token0, token1, block_number)
                        self.store.add_event(block_number, block_hash, item["transactionHash"].hex(),
                                             int(item["logIndex"]), "pool_created", record, utc_now())
                except Exception:
                    LOG.exception("Factory scan failed: %s at block %s", factory, block_number)
                    raise
        return found

    def run(self) -> None:
        cursor = self.store.get_state("last_processed_block")
        if cursor is not None:
            next_block = int(cursor) + 1
        elif self.start_block is not None:
            next_block = self.start_block
        else:
            next_block = max(0, self.w3.eth.block_number - self.confirmations)
        LOG.info("Megan watcher online | chain_id=%s | starting_block=%s | confirmations=%s",
                 self.chain_id, next_block, self.confirmations)
        while self.running:
            try:
                safe_tip = max(0, self.w3.eth.block_number - self.confirmations)
                while self.running and next_block <= safe_tip:
                    block = self.w3.eth.get_block(next_block, full_transactions=True)
                    block_hash = block["hash"].hex()
                    # Persist progress only after both discovery passes complete.
                    token_count = self.scan_deployments(block)
                    traced_count = self.scan_traced_deployments(next_block, block_hash)
                    pool_count = self.scan_factory_logs(next_block, block_hash)
                    self.store.set_state("last_processed_block", str(next_block))
                    LOG.info("BLOCK %s processed | new_tokens=%s | traced_deployments=%s | new_pools=%s",
                             next_block, token_count, traced_count, pool_count)
                    next_block += 1
            except Exception:
                LOG.exception("Polling cycle failed; cursor retained for retry")
            time.sleep(self.poll_seconds)

    def close(self) -> None:
        self.store.close()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Megan Ethereum token and pool discovery MVP")
    parser.add_argument("--start-block", type=int, default=int(os.environ["START_BLOCK"]) if os.getenv("START_BLOCK") else None,
                        help="First block to scan on first run; otherwise starts at current tip")
    parser.add_argument("--once", action="store_true", help="Scan only the next eligible block(s), then exit")
    args = parser.parse_args()

    rpc_url = os.getenv("ETHEREUM_RPC_URL", "").strip()
    if not rpc_url:
        parser.error("Set ETHEREUM_RPC_URL in the environment or .env file")
    poll_seconds = float(os.getenv("POLL_SECONDS", "2"))
    confirmations = int(os.getenv("CONFIRMATIONS", "2"))
    db_path = os.getenv("DATABASE_PATH", "data/megan.sqlite3")
    v2_factories = env_addresses("V2_FACTORY_ADDRESSES")
    v3_factories = env_addresses("V3_FACTORY_ADDRESSES")
    trace_mode = os.getenv("TRACE_MODE", "auto").strip().lower()
    trace_required = os.getenv("TRACE_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}

    watcher = EthereumWatcher(rpc_url, db_path, poll_seconds, confirmations,
                              args.start_block, v2_factories, v3_factories, trace_mode, trace_required)
    signal.signal(signal.SIGINT, watcher.stop)
    signal.signal(signal.SIGTERM, watcher.stop)
    try:
        if args.once:
            watcher.poll_seconds = 0
            cursor = watcher.store.get_state("last_processed_block")
            block_number = int(cursor) + 1 if cursor is not None else (args.start_block if args.start_block is not None else max(0, watcher.w3.eth.block_number - confirmations))
            safe_tip = max(0, watcher.w3.eth.block_number - confirmations)
            while block_number <= safe_tip:
                block = watcher.w3.eth.get_block(block_number, full_transactions=True)
                watcher.scan_deployments(block)
                watcher.scan_traced_deployments(block_number, block["hash"].hex())
                watcher.scan_factory_logs(block_number, block["hash"].hex())
                watcher.store.set_state("last_processed_block", str(block_number))
                block_number += 1
            return 0
        watcher.run()
        return 0
    finally:
        watcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
