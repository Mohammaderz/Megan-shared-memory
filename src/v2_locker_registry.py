"""Generic, bytecode-pinned Uniswap V2 LP locker reader.

The adapter intentionally supports only a declared static ABI shape:
lockCount(address pair) -> uint256 and
lockInfo(address pair, uint256 index) -> (address beneficiary, uint256 amount, uint256 unlockTime).
Protocol-specific deployments must be independently audited and pinned by code hash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lp_analysis import VerifiedLock


@dataclass(frozen=True)
class V2LockerAdapter:
    address: str
    expected_code_hash: str
    lock_count_selector: str
    lock_info_selector: str
    max_locks: int = 10000


@dataclass(frozen=True)
class V2LockerRead:
    locks: tuple[VerifiedLock, ...]
    complete: bool
    warnings: tuple[str, ...]


def load_v2_locker_registry(path: str | None, chain_id: int, pair_address: str,
                            checksum) -> tuple[V2LockerAdapter, ...]:
    if not path:
        return ()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(data.get("chain_id", -1)) != chain_id:
        raise ValueError("V2 locker registry chain_id does not match RPC chain")
    if checksum(data.get("pair_address", "")).lower() != checksum(pair_address).lower():
        raise ValueError("V2 locker registry pair_address does not match requested LP token")
    rows = data.get("lockers")
    if not isinstance(rows, list):
        raise ValueError("V2 locker registry must contain a lockers array")
    result = []
    seen = set()
    for row in rows:
        address = checksum(row["address"])
        code_hash = row["expected_code_hash"].lower()
        count_selector = row["lock_count_selector"].lower()
        info_selector = row["lock_info_selector"].lower()
        max_locks = int(row.get("max_locks", 10000))
        if address.lower() in seen:
            raise ValueError("Duplicate locker address in V2 registry")
        seen.add(address.lower())
        if len(code_hash) != 66 or not code_hash.startswith("0x"):
            raise ValueError("expected_code_hash must be a 32-byte hex hash")
        if any(len(selector) != 10 or not selector.startswith("0x")
               for selector in (count_selector, info_selector)):
            raise ValueError("Locker selectors must be 4-byte hex values")
        if max_locks < 0 or max_locks > 100000:
            raise ValueError("max_locks must be between 0 and 100000")
        result.append(V2LockerAdapter(address, code_hash, count_selector,
                                      info_selector, max_locks))
    return tuple(result)


def _hex(value: Any) -> str:
    return value.hex() if hasattr(value, "hex") else str(value)


def _word(data: bytes, index: int) -> bytes:
    word = data[index * 32:(index + 1) * 32]
    if len(word) != 32:
        raise ValueError("Locker returned malformed ABI data")
    return word


def read_v2_locker_records(w3, pair_address: str, block_number: int,
                           adapters: tuple[V2LockerAdapter, ...], *, registry_complete: bool = False) -> V2LockerRead:
    pair = w3.to_checksum_address(pair_address)
    locks: list[VerifiedLock] = []
    warnings: list[str] = []
    complete = bool(registry_complete)
    if not registry_complete:
        warnings.append("locker_registry_not_declared_complete")
    for adapter in adapters:
        code = bytes(w3.eth.get_code(adapter.address, block_identifier=block_number))
        if not code or _hex(w3.keccak(code)).lower() != adapter.expected_code_hash:
            complete = False
            warnings.append(f"{adapter.address}:locker_code_hash_mismatch_or_missing")
            continue
        pair_word = bytes.fromhex(pair[2:]).rjust(32, b"\\x00")
        try:
            count_raw = bytes(w3.eth.call({
                "to": adapter.address,
                "data": adapter.lock_count_selector + pair_word.hex(),
            }, block_identifier=block_number))
            if len(count_raw) < 32:
                raise ValueError("lockCount returned less than one ABI word")
            count = int.from_bytes(count_raw[-32:], "big")
            if count > adapter.max_locks:
                raise ValueError("lock count exceeds configured safety limit")
            for index in range(count):
                calldata = (adapter.lock_info_selector + pair_word.hex()
                            + index.to_bytes(32, "big").hex())
                raw = bytes(w3.eth.call({
                    "to": adapter.address, "data": calldata,
                }, block_identifier=block_number))
                beneficiary_word = _word(raw, 0)
                if beneficiary_word[:12] != bytes(12):
                    raise ValueError("Malformed beneficiary address in lock record")
                amount = int.from_bytes(_word(raw, 1), "big")
                unlock_time = int.from_bytes(_word(raw, 2), "big")
                if amount <= 0:
                    raise ValueError("Locker record has non-positive LP amount")
                locks.append(VerifiedLock(adapter.address, amount, unlock_time, True))
        except Exception as exc:
            complete = False
            warnings.append(f"{adapter.address}:locker_read_failed:{str(exc)[:160]}")
    return V2LockerRead(tuple(locks), complete, tuple(warnings))
