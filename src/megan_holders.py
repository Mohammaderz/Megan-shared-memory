"""CLI for a read-only, block-pinned Ethereum ERC-20 holder snapshot."""
from __future__ import annotations

import argparse
import json
import os

from web3 import Web3

from holder_snapshot import fetch_erc20_holder_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot ERC-20 holders at an Ethereum block")
    parser.add_argument("--token", required=True, help="ERC-20 contract address")
    parser.add_argument("--deployment-block", required=True, type=int)
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--rpc-url", default=os.getenv("ETHEREUM_RPC_URL"))
    parser.add_argument("--deployer", default=None)
    args = parser.parse_args()
    if not args.rpc_url:
        parser.error("Set ETHEREUM_RPC_URL or pass --rpc-url")

    w3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        parser.error("Could not connect to the configured Ethereum RPC")

    result = fetch_erc20_holder_snapshot(
        w3, args.token, args.deployment_block, to_block=args.to_block,
        chunk_size=args.chunk_size, deployer_address=args.deployer,
    )
    output = {
        "chain_id": result.chain_id,
        "token_address": result.token_address,
        "from_block": result.from_block,
        "to_block": result.to_block,
        "block_hash": result.block_hash,
        "block_timestamp": result.block_timestamp,
        "total_supply_raw": result.total_supply_raw,
        "holder_count": result.holder_count,
        "transfer_log_count": result.transfer_log_count,
        "complete": result.complete,
        "report": result.report.__dict__,
        "warnings": result.warnings,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
