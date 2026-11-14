"""Read-only deployer history from Megan's locally observed deployment database.

This module reports only observed deployment records and block coverage. It does
not label a creator as a rugger: rug history requires independent outcome evidence.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class DeploymentRecord:
    contract_address: str
    tx_hash: str
    block_number: int
    creation_method: str
    trace_provider: str


@dataclass(frozen=True)
class DeployerHistory:
    status: str
    creator: str
    observed_deployment_count: int
    records_truncated: bool
    first_observed_block: int | None
    last_observed_block: int | None
    coverage_start_block: int | None
    coverage_end_block: int | None
    coverage_contiguous: bool
    prior_rug_count: None
    funding_relationships: str
    deployments: tuple[DeploymentRecord, ...]
    warnings: tuple[str, ...]


def lookup_deployer_history(
    database_path: str,
    creator_address: str,
    *,
    before_block: int | None = None,
    limit: int = 100,
) -> DeployerHistory:
    """Read observed CREATE/CREATE2 history for one address from the watcher DB."""
    if not _ADDRESS.fullmatch(creator_address):
        raise ValueError("creator_address must be a 20-byte Ethereum address")
    if limit < 1 or (before_block is not None and before_block < 0):
        raise ValueError("Invalid history limit or block")
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(database_path)

    creator = creator_address.lower()
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "deployments" not in tables:
            raise RuntimeError("Database does not contain Megan deployments table")
        where = "lower(creator)=?"
        args: list[object] = [creator]
        if before_block is not None:
            where += " AND block_number < ?"
            args.append(before_block)
        summary = db.execute(
            f"SELECT COUNT(*) AS n, MIN(block_number) AS lo, MAX(block_number) AS hi "
            f"FROM deployments WHERE {where}", args,
        ).fetchone()
        total_count = int(summary["n"])
        rows = db.execute(
            f"SELECT address,tx_hash,block_number,creation_method,trace_provider "
            f"FROM deployments WHERE {where} ORDER BY block_number DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
        deployments = tuple(
            DeploymentRecord(
                row["address"], row["tx_hash"], int(row["block_number"]),
                row["creation_method"], row["trace_provider"],
            )
            for row in rows
        )

        coverage_start = coverage_end = None
        contiguous = False
        warnings: list[str] = []
        if "block_coverage" in tables:
            coverage = db.execute(
                "SELECT MIN(block_number) AS lo, MAX(block_number) AS hi, "
                "COUNT(DISTINCT block_number) AS n, "
                "SUM(CASE WHEN trace_status='complete' THEN 1 ELSE 0 END) AS complete_n "
                "FROM block_coverage"
            ).fetchone()
            if coverage and coverage["lo"] is not None:
                coverage_start, coverage_end = int(coverage["lo"]), int(coverage["hi"])
                expected = coverage_end - coverage_start + 1
                contiguous = (int(coverage["n"]) == expected
                              and int(coverage["complete_n"] or 0) == expected)
        else:
            warnings.append("trace_block_coverage_table_missing")

        truncated = total_count > len(deployments)
        if truncated:
            warnings.append("deployment_record_list_truncated_by_limit")
        if total_count == 0:
            warnings.append("no_deployments_observed_for_creator")
        if not contiguous:
            warnings.append("observed_trace_coverage_is_not_proven_complete_and_contiguous")
        warnings.append("prior_rug_outcomes_not_verified_by_deployment_database")
        warnings.append("funding_relationships_not_traced")

        return DeployerHistory(
            "observed_history_only", creator, total_count, truncated,
            int(summary["lo"]) if summary["lo"] is not None else None,
            int(summary["hi"]) if summary["hi"] is not None else None,
            coverage_start, coverage_end, contiguous, None, "unknown",
            deployments, tuple(warnings),
        )
    finally:
        db.close()
