"""Read-only Uniswap V3 position NFT custody scanner."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from web3 import Web3

from v3_position_snapshot import (
    UNISWAP_V3_POSITION_MANAGER,
    fetch_v3_position_snapshot,
    load_locker_registry,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Uniswap V3 position NFT custody")
    parser.add_argument("--from-block", required=True, type=int,
                        help="Position-manager deployment block (must cover all mints)")
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--manager", default=UNISWAP_V3_POSITION_MANAGER)
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--lockers-file", default=None,
                        help="Optional JSON registry with verified code hashes and read selectors")
    parser.add_argument("--rpc-url", default=os.getenv("ETHEREUM_RPC_URL"))
    args = parser.parse_args()
    if not args.rpc_url:
        parser.error("Set ETHEREUM_RPC_URL or pass --rpc-url")
    w3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        parser.error("Could not connect to the configured Ethereum RPC")
    registry = load_locker_registry(args.lockers_file, int(w3.eth.chain_id),
                                    w3.to_checksum_address)
    snapshot = fetch_v3_position_snapshot(
        w3, args.manager, args.from_block, to_block=args.to_block,
        chunk_size=args.chunk_size, lockers=registry,
    )
    print(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
