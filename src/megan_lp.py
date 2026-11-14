"""Read-only Uniswap V2 LP-token custody snapshot."""
from __future__ import annotations

import argparse
import json
import os

from web3 import Web3

from holder_snapshot import fetch_erc20_holder_snapshot
from lp_analysis import LPHolder, classify_lp_supply


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Uniswap V2 LP-token custody")
    parser.add_argument("--pair", required=True, help="Uniswap V2 pair/LP-token address")
    parser.add_argument("--created-block", required=True, type=int)
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--rpc-url", default=os.getenv("ETHEREUM_RPC_URL"))
    args = parser.parse_args()
    if not args.rpc_url:
        parser.error("Set ETHEREUM_RPC_URL or pass --rpc-url")

    w3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        parser.error("Could not connect to the configured Ethereum RPC")

    snapshot = fetch_erc20_holder_snapshot(
        w3, args.pair, args.created_block, to_block=args.to_block,
        chunk_size=args.chunk_size,
    )
    holders = [
        LPHolder(row.address, row.balance_raw, row.role)
        for row in snapshot.holder_balances
    ]
    classification = classify_lp_supply(
        snapshot.total_supply_raw, holders, [],
        holders_complete=snapshot.complete,
        locks_complete=False,
        snapshot_timestamp=snapshot.block_timestamp,
    )
    print(json.dumps({
        "chain_id": snapshot.chain_id,
        "pair_address": snapshot.token_address,
        "from_block": snapshot.from_block,
        "to_block": snapshot.to_block,
        "block_hash": snapshot.block_hash,
        "total_lp_supply_raw": snapshot.total_supply_raw,
        "holder_count": snapshot.holder_count,
        "snapshot_complete": snapshot.complete,
        "lp_custody": classification.__dict__,
        "holder_warnings": snapshot.warnings,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
