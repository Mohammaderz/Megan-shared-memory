"""Conservative Uniswap-V2-style LP-token custody classification.

This module consumes verified on-chain snapshots; it does not guess locker status
from an address name or from a token's reported liquidity. V3 position NFTs need
a separate adapter and are intentionally not treated as fungible LP balances.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


BURN_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}


@dataclass(frozen=True)
class LPHolder:
    address: str
    balance_raw: int
    holder_type: str  # "eoa", "contract", or "burn"


@dataclass(frozen=True)
class VerifiedLock:
    locker_address: str
    amount_raw: int
    unlock_timestamp: int
    verified: bool


@dataclass(frozen=True)
class LPClassification:
    status: str  # locked, unlocked, mixed, unknown, burned
    total_supply_raw: int
    locked_share_pct: float | None
    unlocked_share_pct: float | None
    burned_share_pct: float | None
    unknown_share_pct: float | None
    earliest_unlock_timestamp: int | None
    warnings: tuple[str, ...]


def classify_lp_supply(
    total_supply_raw: int,
    holders: Iterable[LPHolder],
    locks: Iterable[VerifiedLock],
    *,
    holders_complete: bool,
    locks_complete: bool,
    snapshot_timestamp: int,
) -> LPClassification:
    """Classify LP-token units only when holder and locker evidence is complete.

    A contract custody address is UNKNOWN unless verified lock records account
    for its LP balance. Verified lock amounts must not exceed that custody
    address's observed balance. Expired locks are treated as unlocked.
    """
    warnings: list[str] = []
    if total_supply_raw <= 0 or snapshot_timestamp < 0:
        return _unknown(total_supply_raw, "invalid_supply_or_snapshot")

    holder_rows = list(holders)
    lock_rows = list(locks)
    balances: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for row in holder_rows:
        address = row.address.lower()
        if len(address) != 42 or not address.startswith("0x") or row.balance_raw < 0:
            return _unknown(total_supply_raw, "invalid_holder_record")
        if row.holder_type not in {"eoa", "contract", "burn"}:
            return _unknown(total_supply_raw, "unknown_holder_type")
        if address in balances:
            return _unknown(total_supply_raw, "duplicate_holder")
        balances[address] = row.balance_raw
        kinds[address] = row.holder_type

    if not holders_complete:
        return _unknown(total_supply_raw, "holder_snapshot_incomplete")
    if sum(balances.values()) != total_supply_raw:
        return _unknown(total_supply_raw, "holder_balances_do_not_reconcile_to_supply")
    if not locks_complete:
        return _unknown(total_supply_raw, "locker_registry_or_records_incomplete")

    locked_by_address: dict[str, int] = {}
    expiry_by_address: dict[str, list[int]] = {}
    for lock in lock_rows:
        address = lock.locker_address.lower()
        if not lock.verified:
            return _unknown(total_supply_raw, "unverified_locker_record")
        if len(address) != 42 or not address.startswith("0x") or lock.amount_raw <= 0:
            return _unknown(total_supply_raw, "invalid_lock_record")
        if kinds.get(address) != "contract":
            return _unknown(total_supply_raw, "lock_address_not_verified_contract_holder")
        locked_by_address[address] = locked_by_address.get(address, 0) + lock.amount_raw
        expiry_by_address.setdefault(address, []).append(lock.unlock_timestamp)

    locked = 0
    unlocked = 0
    burned = 0
    unknown = 0
    active_expiries: list[int] = []
    for address, balance in balances.items():
        kind = kinds[address]
        if kind == "burn" or address in BURN_ADDRESSES:
            burned += balance
            continue
        recorded_lock = locked_by_address.get(address, 0)
        if recorded_lock > balance:
            return _unknown(total_supply_raw, "lock_amount_exceeds_locker_balance")
        active_lock = 0
        if recorded_lock:
            for lock in lock_rows:
                if lock.locker_address.lower() == address:
                    if lock.unlock_timestamp > snapshot_timestamp:
                        active_lock += lock.amount_raw
                        active_expiries.append(lock.unlock_timestamp)
                    else:
                        unlocked += lock.amount_raw
        if kind == "eoa":
            if recorded_lock:
                return _unknown(total_supply_raw, "lock_record_assigned_to_eoa")
            unlocked += balance
        else:
            locked += active_lock
            accounted = recorded_lock
            unclassified = balance - accounted
            # Any LP tokens held by a contract but not covered by a verified,
            # current or expired lock record remain UNKNOWN.
            unknown += unclassified

    if locked + unlocked + burned + unknown != total_supply_raw:
        return _unknown(total_supply_raw, "classification_does_not_reconcile")
    pct = lambda amount: round(amount * 100.0 / total_supply_raw, 6)
    known_locked = pct(locked)
    known_unlocked = pct(unlocked)
    known_burned = pct(burned)
    unknown_pct = pct(unknown)
    if unknown:
        status = "unknown"
        warnings.append("unclassified_contract_custody")
    elif locked and unlocked:
        status = "mixed"
    elif locked:
        status = "locked"
    elif unlocked:
        status = "unlocked"
    else:
        status = "burned"
    if unlocked:
        warnings.append("lp_tokens_not_time_locked")
    if burned:
        warnings.append("lp_tokens_burned_not_locker_locked")
    return LPClassification(
        status, total_supply_raw, known_locked, known_unlocked, known_burned,
        unknown_pct, min(active_expiries) if active_expiries else None,
        tuple(warnings),
    )


def _unknown(total_supply_raw: int, reason: str) -> LPClassification:
    return LPClassification(
        "unknown", max(0, total_supply_raw), None, None, None, None, None,
        (reason,),
    )
