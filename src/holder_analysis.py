"""Conservative ERC-20 holder concentration from a complete balance snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


EXCLUDED_ROLES = {"burn", "lp_pair", "verified_locker"}
VALID_ROLES = EXCLUDED_ROLES | {"eoa", "contract"}


@dataclass(frozen=True)
class HolderBalance:
    address: str
    balance_raw: int
    role: str  # eoa, contract, burn, lp_pair, verified_locker


@dataclass(frozen=True)
class HolderReport:
    status: str
    total_supply_raw: int
    circulating_supply_raw: int | None
    top10_share_circulating_pct: float | None
    top10_share_total_supply_pct: float | None
    deployer_share_total_supply_pct: float | None
    holder_count: int | None
    excluded_burn_raw: int | None
    excluded_lp_pair_raw: int | None
    excluded_verified_locker_raw: int | None
    top_holders: tuple[tuple[str, int, str], ...]
    warnings: tuple[str, ...]


def analyze_holders(
    total_supply_raw: int,
    holders: Iterable[HolderBalance],
    *,
    snapshot_complete: bool,
    deployer_address: str | None = None,
) -> HolderReport:
    """Calculate concentration only if holder balances reconcile to total supply.

    LP pair, burn and verified-locker roles are excluded from circulating supply.
    A locker role must only be assigned after independently verifying its code
    and lock records. Unknown or unverified roles are rejected, not excluded.
    """
    if total_supply_raw <= 0:
        return _unknown(max(0, total_supply_raw), "invalid_total_supply")
    rows = list(holders)
    if not snapshot_complete:
        return _unknown(total_supply_raw, "holder_snapshot_incomplete")

    seen: set[str] = set()
    for row in rows:
        address = row.address.lower()
        if len(address) != 42 or not address.startswith("0x"):
            return _unknown(total_supply_raw, "invalid_holder_address")
        if address in seen:
            return _unknown(total_supply_raw, "duplicate_holder_address")
        seen.add(address)
        if row.balance_raw < 0:
            return _unknown(total_supply_raw, "negative_holder_balance")
        if row.role not in VALID_ROLES:
            return _unknown(total_supply_raw, "unverified_holder_role")

    if sum(row.balance_raw for row in rows) != total_supply_raw:
        return _unknown(total_supply_raw, "holder_balances_do_not_reconcile")

    burn = sum(r.balance_raw for r in rows if r.role == "burn")
    lp_pair = sum(r.balance_raw for r in rows if r.role == "lp_pair")
    lockers = sum(r.balance_raw for r in rows if r.role == "verified_locker")
    circulating = total_supply_raw - burn - lp_pair - lockers
    eligible = [r for r in rows if r.role not in EXCLUDED_ROLES]
    eligible.sort(key=lambda r: r.balance_raw, reverse=True)
    top10 = sum(r.balance_raw for r in eligible[:10])
    top10_circ = round(top10 * 100.0 / circulating, 6) if circulating else None
    top10_total = round(top10 * 100.0 / total_supply_raw, 6)
    deployer_share = None
    if deployer_address:
        target = deployer_address.lower()
        match = next((r for r in rows if r.address.lower() == target), None)
        if match is not None:
            deployer_share = round(match.balance_raw * 100.0 / total_supply_raw, 6)
    warnings: list[str] = []
    if circulating <= 0:
        warnings.append("no_circulating_supply_after_verified_exclusions")
    if deployer_address and deployer_share is None:
        warnings.append("deployer_not_found_in_complete_holder_snapshot")
    if any(r.role == "contract" for r in eligible):
        warnings.append("contract_holders_included_until_relationships_are_verified")
    return HolderReport(
        "complete", total_supply_raw, circulating, top10_circ, top10_total,
        deployer_share, len(rows), burn, lp_pair, lockers,
        tuple((r.address.lower(), r.balance_raw, r.role) for r in eligible[:10]),
        tuple(warnings),
    )


def _unknown(total_supply_raw: int, reason: str) -> HolderReport:
    return HolderReport(
        "unknown", total_supply_raw, None, None, None, None, None,
        None, None, None, (), (reason,),
    )
