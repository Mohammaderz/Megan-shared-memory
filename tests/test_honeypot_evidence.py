from public_sources import parse_honeypot_evidence


def test_honeypot_simulation_status_is_not_directional_trade_success():
    payload = {
        "simulationSuccess": True,
        "honeypotResult": {"isHoneypot": False},
        "simulationResult": {"buyTax": 0, "sellTax": 0},
    }
    evidence = parse_honeypot_evidence(payload)
    assert evidence["simulation_success"] is True
    assert evidence["simulation_buy_ok"] is None
    assert evidence["simulation_sell_ok"] is None
    assert evidence["honeypot"] is False


def test_missing_honeypot_fields_remain_unknown():
    evidence = parse_honeypot_evidence({})
    assert evidence["honeypot"] is None
    assert evidence["simulation_buy_ok"] is None
    assert evidence["simulation_sell_ok"] is None
    assert evidence["buy_tax_pct"] is None
    assert evidence["sell_tax_pct"] is None


def test_honeypot_tax_values_are_parsed_without_claiming_execution_success():
    evidence = parse_honeypot_evidence({
        "simulationSuccess": True,
        "simulationResult": {"buyTax": "1.5", "sellTax": "7"},
    })
    assert evidence["buy_tax_pct"] == 1.5
    assert evidence["sell_tax_pct"] == 7.0
    assert evidence["simulation_buy_ok"] is None
    assert evidence["simulation_sell_ok"] is None
