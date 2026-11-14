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
        row = db.db.execute(
            "SELECT source_json,market_json FROM candidates WHERE token_address=?", (address,)
        ).fetchone()
        assert result["token"] == address
        assert json.loads(row[0])["source"] == "telegram"
        assert json.loads(row[1]) == {}
    finally:
        db.close()
