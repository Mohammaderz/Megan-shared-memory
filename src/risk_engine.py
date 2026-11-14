"""Evidence-based token risk scoring. Missing data is UNKNOWN, never SAFE."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class RiskEvidence:
    contract_verified: bool | None = None
    honeypot: bool | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    simulation_buy_ok: bool | None = None
    simulation_sell_ok: bool | None = None
    owner_can_mint: bool | None = None
    owner_can_pause: bool | None = None
    owner_can_blacklist: bool | None = None
    owner_can_change_tax: bool | None = None
    proxy_upgradeable: bool | None = None
    lp_locked_share_pct: float | None = None
    lp_lock_expiry_days: float | None = None
    liquidity_usd: float | None = None
    liquidity_change_1h_pct: float | None = None
    top10_holder_share_pct: float | None = None
    deployer_supply_share_pct: float | None = None
    deployer_prior_rugs: int | None = None
    unique_buyers_1h: int | None = None
    unique_sellers_1h: int | None = None
    volume_liquidity_ratio_1h: float | None = None
    wash_trade_suspected: bool | None = None
    social_mentions_1h: int | None = None
    social_sources: int | None = None
    liquidity_lock_status: str = "unknown"  # locked, unlocked, unknown, not_applicable
    notes: list[str] = field(default_factory=list)

@dataclass
class RiskReport:
    risk_score: int
    risk_level: str
    opportunity_score: int
    confidence: str
    hard_blocks: list[str]
    warnings: list[str]
    unknowns: list[str]
    evidence: dict[str, Any]


def assess(e: RiskEvidence) -> RiskReport:
    """0..100 risk and opportunity scores; conservative, explainable heuristic."""
    risk = 0
    hard: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []
    def unknown_if_none(name: str, value: Any) -> None:
        if value is None: unknown.append(name)

    for name in ("honeypot", "simulation_buy_ok", "simulation_sell_ok", "owner_can_mint",
                 "owner_can_pause", "owner_can_blacklist", "owner_can_change_tax",
                 "proxy_upgradeable", "lp_locked_share_pct", "liquidity_usd",
                 "top10_holder_share_pct", "deployer_supply_share_pct",
                 "deployer_prior_rugs", "unique_buyers_1h", "unique_sellers_1h",
                 "wash_trade_suspected"):
        unknown_if_none(name, getattr(e, name))

    if e.honeypot is True or e.simulation_sell_ok is False:
        hard.append("sell_blocked_or_honeypot")
        risk += 100
    if e.simulation_buy_ok is False:
        hard.append("buy_simulation_failed")
        risk += 100
    if e.owner_can_mint is True: risk += 18; warnings.append("owner_can_mint")
    if e.owner_can_pause is True: risk += 12; warnings.append("owner_can_pause")
    if e.owner_can_blacklist is True: risk += 18; warnings.append("owner_can_blacklist")
    if e.owner_can_change_tax is True: risk += 15; warnings.append("owner_can_change_tax")
    if e.proxy_upgradeable is True: risk += 8; warnings.append("upgradeable_proxy")
    if e.sell_tax_pct is not None:
        if e.sell_tax_pct >= 20: risk += 35; warnings.append("extreme_sell_tax")
        elif e.sell_tax_pct >= 8: risk += 18; warnings.append("high_sell_tax")
        elif e.sell_tax_pct > 3: risk += 8; warnings.append("elevated_sell_tax")
    if e.lp_locked_share_pct is None:
        unknown.append("liquidity_lock")
    elif e.lp_locked_share_pct < 50:
        risk += 22; warnings.append("majority_liquidity_unlocked")
    elif e.lp_locked_share_pct < 90:
        risk += 10; warnings.append("partial_liquidity_lock")
    if e.liquidity_lock_status == "unlocked":
        risk += 10; warnings.append("liquidity_unlocked")
    if e.lp_lock_expiry_days is not None and e.lp_lock_expiry_days < 7:
        risk += 12; warnings.append("liquidity_lock_expires_soon")
    if e.liquidity_usd is not None:
        if e.liquidity_usd < 5_000: risk += 22; warnings.append("very_thin_liquidity")
        elif e.liquidity_usd < 20_000: risk += 12; warnings.append("thin_liquidity")
    if e.liquidity_change_1h_pct is not None and e.liquidity_change_1h_pct <= -30:
        risk += 25; warnings.append("rapid_liquidity_outflow")
    if e.top10_holder_share_pct is not None:
        if e.top10_holder_share_pct >= 70: risk += 25; warnings.append("extreme_holder_concentration")
        elif e.top10_holder_share_pct >= 50: risk += 15; warnings.append("high_holder_concentration")
    if e.deployer_supply_share_pct is not None and e.deployer_supply_share_pct >= 10:
        risk += 12; warnings.append("deployer_holds_large_supply")
    if e.deployer_prior_rugs:
        risk += min(30, 15 * e.deployer_prior_rugs); warnings.append("deployer_prior_rug_history")
    if e.wash_trade_suspected is True:
        risk += 20; warnings.append("possible_wash_trading")
    if e.unique_buyers_1h is not None and e.unique_sellers_1h is not None:
        if e.unique_buyers_1h >= 10 and e.unique_sellers_1h == 0:
            risk += 20; warnings.append("no_observed_sellers")
    risk = min(100, risk)

    # Opportunity is intentionally capped when critical safety evidence is missing.
    momentum = 0
    if e.unique_buyers_1h is not None: momentum += min(25, e.unique_buyers_1h * 1.5)
    if e.social_mentions_1h is not None and e.social_sources is not None:
        momentum += min(15, e.social_mentions_1h * 0.5) if e.social_sources >= 2 else min(4, e.social_mentions_1h * 0.2)
    if e.volume_liquidity_ratio_1h is not None:
        momentum += min(15, max(0, e.volume_liquidity_ratio_1h) * 5)
    if e.liquidity_usd is not None and e.liquidity_usd >= 20_000: momentum += 10
    opportunity = max(0, min(100, round(momentum * (1 - risk / 100))))
    # LP lock/burn is reported as risk evidence, but never blocks discovery or
    # opportunity calculation: the user wants the signal before those actions occur.
    critical = {"honeypot", "simulation_sell_ok", "lp_locked_share_pct", "liquidity_usd",
                "top10_holder_share_pct", "owner_can_mint", "owner_can_blacklist"}
    missing_critical = critical.intersection(unknown)
    if len(missing_critical) >= 5: confidence = "low"
    elif missing_critical: confidence = "medium"
    else: confidence = "high"
    level = "critical" if risk >= 75 else "high" if risk >= 50 else "medium" if risk >= 25 else "low"
    return RiskReport(risk, level, opportunity, confidence, hard, sorted(set(warnings)),
                      sorted(set(unknown)), asdict(e))
