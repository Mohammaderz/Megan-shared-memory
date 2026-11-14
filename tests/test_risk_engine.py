from risk_engine import RiskEvidence, assess

def test_unlocked_liquidity_is_a_risk_not_an_opportunity_signal():
    report=assess(RiskEvidence(lp_locked_share_pct=0,liquidity_lock_status="unlocked",liquidity_usd=30000,
        honeypot=False,simulation_sell_ok=True,owner_can_mint=False,owner_can_blacklist=False))
    assert report.risk_score >= 30
    assert "majority_liquidity_unlocked" in report.warnings
    assert report.opportunity_score == 0

def test_missing_security_evidence_reduces_confidence():
    report=assess(RiskEvidence(liquidity_usd=10000))
    assert report.confidence == "low"
    assert "honeypot" in report.unknowns
    assert "lp_locked_share_pct" in report.unknowns

def test_honeypot_is_hard_block():
    report=assess(RiskEvidence(honeypot=True,simulation_sell_ok=False))
    assert report.risk_score == 100
    assert "sell_blocked_or_honeypot" in report.hard_blocks

def test_risk_score_is_bounded():
    report=assess(RiskEvidence(honeypot=True,simulation_sell_ok=False,owner_can_mint=True,
        owner_can_pause=True,owner_can_blacklist=True,owner_can_change_tax=True,
        sell_tax_pct=99,lp_locked_share_pct=0,liquidity_usd=1,top10_holder_share_pct=99,
        deployer_supply_share_pct=90,deployer_prior_rugs=8,wash_trade_suspected=True))
    assert 0 <= report.risk_score <= 100
