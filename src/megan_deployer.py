"""CLI for inspecting locally observed creator deployment history."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from deployer_history import lookup_deployer_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect observed Ethereum deployer history")
    parser.add_argument("--creator", required=True, help="Creator/deployer address")
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/megan.sqlite3"))
    parser.add_argument("--before-block", type=int, default=None)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    result = lookup_deployer_history(
        args.db, args.creator, before_block=args.before_block, limit=args.limit,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
