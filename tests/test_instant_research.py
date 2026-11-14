import json

import megan_research
from megan_research import ResearchDB, analyze_token_address


def test_honeypot_tax_presence_is_not_mistaken_for_successful_simulation(tmp_path, monkeypatch):
    monkeypatch.setattr(megan_research, "dexscreener_token_pairs", lambda _address: [])
    monkeypatch.setattr(megan_research, "honeypot_check", lambda _address: {
        "honeypotResult": {"isHoneypot": False},
        "simulationResult": {"buyTax": 0, "sellTax": 0},
        # Deliberately omit simulationSuccess: no verified simulation outcome.
    })
    db = ResearchDB(str(tmp_path / "research.sqlite3"))
    try:
        address = "0x" + "ab" * 20
        analyze_token_address(db, address, {"source": "test"})
        row = db.db.execute(
            "SELECT risk_json FROM candidates WHERE token_address=?", (address,)
        ).fetchone()
        report = json.loads(row[0])
        assert report["evidence"]["simulation_buy_ok"] is None
        assert report["evidence"]["simulation_sell_ok"] is None
        assert "simulation_sell_ok" in report["unknowns"]
    finally:
        db.close()


def test_alert_address_can_be_analyzed_before_any_pool_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(megan_research, "dexscreener_token_pairs", lambda _address: [])
    monkeypatch.setattr(megan_research, "honeypot_check", lambda _address: {})
    db = ResearchDB(str(tmp_path / "research.sqlite3"))
    try:
        address = "0x" + "cd" * 20
        result = analyze_token_address(db, address, {"source": "telegram", "source_name": "@alerts"})
        assert result["token"] == address
        assert result["qualified"] is False
        row = db.db.execute(
            "SELECT token_address FROM candidates WHERE token_address=?", (address,)
        ).fetchone()
        assert row is None
    finally:
        db.close()



def test_token_qualifies_only_when_ethereum_pool_liquidity_is_over_100_usd(tmp_path, monkeypatch):
    address = "0x" + "ef" * 20
    monkeypatch.setattr(megan_research, "dexscreener_token_pairs", lambda _address: [{
        "chainId": "ethereum", "pairAddress": "0x" + "11" * 20,
        "baseToken": {"name": "Test"}, "liquidity": {"usd": 100.01},
        "txns": {}, "volume": {}, "priceChange": {},
    }])
    monkeypatch.setattr(megan_research, "honeypot_check", lambda _address: {})
    db = ResearchDB(str(tmp_path / "research.sqlite3"))
    try:
        result = analyze_token_address(db, address, {"source": "test"})
        assert result["qualified"] is True
        assert result["metrics"]["liquidity_usd"] == 100.01
    finally:
        db.close()


def test_exactly_100_usd_does_not_qualify(tmp_path, monkeypatch):
    address = "0x" + "fe" * 20
    monkeypatch.setattr(megan_research, "dexscreener_token_pairs", lambda _address: [{
        "chainId": "ethereum", "pairAddress": "0x" + "22" * 20,
        "baseToken": {"name": "Test"}, "liquidity": {"usd": 100},
        "txns": {}, "volume": {}, "priceChange": {},
    }])
    db = ResearchDB(str(tmp_path / "research.sqlite3"))
    try:
        result = analyze_token_address(db, address, {"source": "test"})
        assert result["qualified"] is False
        assert result["reason"] == "no_ethereum_pool_over_100_usd"
    finally:
        db.close()
