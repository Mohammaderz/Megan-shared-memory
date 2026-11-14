import json

import megan_research as research


def test_token_address_checks_base_then_quote():
    quote = "0x" + "ab" * 20
    assert research._token_address({
        "base_token_id": "eth_0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "quote_token_id": f"eth_{quote}",
    }) == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def test_tax_presence_does_not_claim_buy_simulation_succeeded(monkeypatch, tmp_path, capsys):
    token = "0x" + "12" * 20
    monkeypatch.setattr(research, "geckoterminal_new_pools", lambda: [{
        "base_token_id": f"eth_{token}",
        "quote_token_id": None,
        "pool_address": "0x" + "34" * 20,
        "reserve_usd": "12000",
    }])
    monkeypatch.setattr(research, "dexscreener_token_pairs", lambda address: [])
    monkeypatch.setattr(research, "honeypot_check", lambda address: {
        "honeypotResult": {"isHoneypot": False},
        "simulationResult": {"buyTax": 1.0, "sellTax": 2.0},
    })

    db = research.ResearchDB(str(tmp_path / "research.sqlite3"))
    try:
        assert research.scan_once(db) == 1
        row = db.db.execute(
            "SELECT risk_json FROM candidates WHERE token_address=?", (token,)
        ).fetchone()
    finally:
        db.close()

    report = json.loads(row[0])
    assert report["evidence"]["honeypot"] is False
    assert report["evidence"]["buy_tax_pct"] == 1.0
    assert report["evidence"]["sell_tax_pct"] == 2.0
    assert report["evidence"]["simulation_buy_ok"] is None
    assert "simulation success remains UNKNOWN" in " ".join(report["evidence"]["notes"])
def test_token_address_selects_non_quote_when_base_is_weth():
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    meme = "0x" + "cd" * 20
    assert research._token_address({
        "base_token_id": f"eth_{weth}",
        "quote_token_id": f"eth_{meme}",
    }) == meme


def test_token_address_returns_unknown_for_two_unrecognized_assets():
    first = "0x" + "11" * 20
    second = "0x" + "22" * 20
    assert research._token_address({
        "base_token_id": f"eth_{first}",
        "quote_token_id": f"eth_{second}",
    }) is None
