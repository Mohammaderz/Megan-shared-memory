import sqlite3

import pytest

from deployer_history import lookup_deployer_history


CREATOR = "0x" + "ab" * 20
TOKEN_A = "0x" + "11" * 20
TOKEN_B = "0x" + "22" * 20


def make_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE deployments (
      address TEXT PRIMARY KEY, creator TEXT NOT NULL, tx_hash TEXT NOT NULL,
      block_number INTEGER NOT NULL, block_hash TEXT NOT NULL,
      creation_method TEXT NOT NULL, trace_provider TEXT NOT NULL, observed_at TEXT NOT NULL
    );
    CREATE TABLE block_coverage (
      block_number INTEGER PRIMARY KEY, block_hash TEXT NOT NULL,
      trace_status TEXT NOT NULL, trace_provider TEXT, trace_error TEXT, observed_at TEXT NOT NULL
    );
    """)
    db.execute(
        "INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?)",
        (TOKEN_A, CREATOR, "0xtx1", 100, "0xhash1", "create", "eth_receipt", "now"),
    )
    db.execute(
        "INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?)",
        (TOKEN_B, CREATOR, "0xtx2", 101, "0xhash2", "create2", "debug_traceBlockByNumber", "now"),
    )
    for block in (100, 101, 102):
        db.execute(
            "INSERT INTO block_coverage VALUES(?,?,?,?,?,?)",
            (block, "0xhash", "complete", "trace", None, "now"),
        )
    db.commit()
    db.close()


def test_deployer_history_reports_observed_records_and_coverage(tmp_path):
    path = tmp_path / "watcher.sqlite3"
    make_db(path)
    result = lookup_deployer_history(str(path), CREATOR)
    assert result.status == "observed_history_only"
    assert result.observed_deployment_count == 2
    assert result.first_observed_block == 100
    assert result.last_observed_block == 101
    assert result.coverage_contiguous is True
    assert result.prior_rug_count is None
    assert result.funding_relationships == "unknown"
    assert {item.creation_method for item in result.deployments} == {"create", "create2"}


def test_deployer_history_respects_block_cutoff_and_limit(tmp_path):
    path = tmp_path / "watcher.sqlite3"
    make_db(path)
    result = lookup_deployer_history(str(path), CREATOR, before_block=101, limit=1)
    assert result.observed_deployment_count == 1
    assert result.last_observed_block == 100


def test_deployer_history_does_not_invent_rug_count(tmp_path):
    path = tmp_path / "watcher.sqlite3"
    make_db(path)
    result = lookup_deployer_history(str(path), CREATOR)
    assert result.prior_rug_count is None
    assert "prior_rug_outcomes_not_verified_by_deployment_database" in result.warnings


def test_invalid_creator_address_rejected(tmp_path):
    path = tmp_path / "watcher.sqlite3"
    make_db(path)
    with pytest.raises(ValueError, match="20-byte Ethereum address"):
        lookup_deployer_history(str(path), "not-an-address")
