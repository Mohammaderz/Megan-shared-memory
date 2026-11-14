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
def test_missing_critical_evidence_caps_opportunity_score():
    report = assess(RiskEvidence(
        unique_buyers_1h=100,
        social_mentions_1h=100,
        social_sources=5,
        volume_liquidity_ratio_1h=3,
        liquidity_usd=50000,
    ))
    assert report.opportunity_score <= 5
    assert report.confidence == "low"


def test_complete_positive_safety_evidence_allows_higher_opportunity_score():
    report = assess(RiskEvidence(
        honeypot=False,
        simulation_sell_ok=True,
        simulation_buy_ok=True,
        lp_locked_share_pct=100,
        liquidity_usd=50000,
        top10_holder_share_pct=20,
        owner_can_mint=False,
        owner_can_pause=False,
        owner_can_blacklist=False,
        owner_can_change_tax=False,
        proxy_upgradeable=False,
        deployer_supply_share_pct=1,
        deployer_prior_rugs=0,
        wash_trade_suspected=False,
        unique_buyers_1h=20,
        social_mentions_1h=10,
        social_sources=3,
        volume_liquidity_ratio_1h=1,
    ))
    assert report.opportunity_score > 5
    assert report.confidence == "high"
def test_missing_owner_controls_and_deployer_history_prevent_high_confidence():
    report = assess(RiskEvidence(
        honeypot=False, simulation_buy_ok=True, simulation_sell_ok=True,
        lp_locked_share_pct=100, liquidity_usd=50000,
        top10_holder_share_pct=20, owner_can_mint=False,
        owner_can_pause=False, owner_can_blacklist=False,
        owner_can_change_tax=False, proxy_upgradeable=False,
        deployer_supply_share_pct=1, deployer_prior_rugs=0,
        wash_trade_suspected=False,
    ))
    assert report.confidence == "high"


def test_unknown_proxy_and_deployer_history_caps_confidence():
    report = assess(RiskEvidence(
        honeypot=False, simulation_buy_ok=True, simulation_sell_ok=True,
        lp_locked_share_pct=100, liquidity_usd=50000,
        top10_holder_share_pct=20, owner_can_mint=False,
        owner_can_pause=False, owner_can_blacklist=False,
        owner_can_change_tax=False,
    ))
    assert report.confidence == "low"
    assert report.opportunity_score <= 3
