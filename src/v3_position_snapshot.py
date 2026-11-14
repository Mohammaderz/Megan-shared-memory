"""Read-only Uniswap V3 position-NFT snapshot and conservative custody analysis.

A position NFT held by a contract is UNKNOWN unless a configured locker adapter
matches the contract's on-chain bytecode hash and its lock-state calls verify.
This module never equates contract custody with a time lock.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
UNISWAP_V3_POSITION_MANAGER = "0xc36442b4a4522e871399cd717abdd847ab11fe88"

POSITION_MANAGER_ABI = [
    {"type":"function","name":"ownerOf","stateMutability":"view",
     "inputs":[{"name":"tokenId","type":"uint256"}],"outputs":[{"name":"","type":"address"}]},
    {"type":"function","name":"positions","stateMutability":"view",
     "inputs":[{"name":"tokenId","type":"uint256"}],"outputs":[
       {"name":"nonce","type":"uint96"},{"name":"operator","type":"address"},
       {"name":"token0","type":"address"},{"name":"token1","type":"address"},
       {"name":"fee","type":"uint24"},{"name":"tickLower","type":"int24"},
       {"name":"tickUpper","type":"int24"},{"name":"liquidity","type":"uint128"},
       {"name":"feeGrowthInside0LastX128","type":"uint256"},
       {"name":"feeGrowthInside1LastX128","type":"uint256"},
       {"name":"tokensOwed0","type":"uint128"},{"name":"tokensOwed1","type":"uint128"}]},
]


@dataclass(frozen=True)
class LockerConfig:
    address: str
    expected_code_hash: str
    is_locked_selector: str
    unlock_time_selector: str


@dataclass(frozen=True)
class V3Position:
    token_id: int
    owner: str | None
    owner_type: str
    custody_status: str
    unlock_timestamp: int | None
    token0: str | None
    token1: str | None
    fee: int | None
    tick_lower: int | None
    tick_upper: int | None
    liquidity_raw: int | None
    tokens_owed0_raw: int | None
    tokens_owed1_raw: int | None
    warning: str | None = None


@dataclass(frozen=True)
class V3Snapshot:
    chain_id: int
    manager_address: str
    from_block: int
    to_block: int
    block_hash: str
    block_timestamp: int
    minted_position_count: int
    active_position_count: int
    locked_count: int
    unlocked_count: int
    burned_count: int
    unknown_count: int
    complete: bool
    positions: tuple[V3Position, ...]
    warnings: tuple[str, ...]


def load_locker_registry(path: str | None, chain_id: int, checksum) -> tuple[LockerConfig, ...]:
    if not path:
        return ()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("chain_id") != chain_id:
        raise ValueError("Locker registry chain_id does not match RPC chain")
    rows = data.get("lockers")
    if not isinstance(rows, list):
        raise ValueError("Locker registry must contain a lockers array")
    result = []
    seen = set()
    for row in rows:
        address = checksum(row["address"])
        code_hash = row["expected_code_hash"].lower()
        locked_selector = row["is_locked_selector"].lower()
        unlock_selector = row["unlock_time_selector"].lower()
        if address.lower() in seen:
            raise ValueError("Duplicate locker address in registry")
        seen.add(address.lower())
        if len(code_hash) != 66 or not code_hash.startswith("0x"):
            raise ValueError("expected_code_hash must be a 32-byte hex hash")
        for selector in (locked_selector, unlock_selector):
            if len(selector) != 10 or not selector.startswith("0x"):
                raise ValueError("Locker selectors must be 4-byte hex values")
        result.append(LockerConfig(address, code_hash, locked_selector, unlock_selector))
    return tuple(result)


def _hex(value: Any) -> str:
    return value.hex() if hasattr(value, "hex") else str(value)


def _topic_bytes(value: Any) -> bytes:
    return bytes.fromhex(_hex(value).removeprefix("0x"))


def _topic_address(topic: Any, checksum) -> str:
    raw = _topic_bytes(topic)
    if len(raw) != 32 or raw[:12] != b"\\x00" * 12:
        raise ValueError("Malformed ERC-721 indexed address")
    return checksum("0x" + raw[-20:].hex())


def _fetch_logs_adaptive(w3, manager: str, start: int, end: int, initial_chunk: int):
    logs = []
    cursor = start
    chunk = max(1, initial_chunk)
    while cursor <= end:
        stop = min(end, cursor + chunk - 1)
        try:
            logs.extend(w3.eth.get_logs({
                "address": manager, "fromBlock": cursor, "toBlock": stop,
                "topics": [TRANSFER_TOPIC],
            }))
            cursor = stop + 1
            chunk = min(initial_chunk, max(1, chunk * 2))
        except Exception:
            if chunk == 1:
                raise
            chunk = max(1, chunk // 2)
    return logs


def _verify_locker(w3, locker: LockerConfig, token_id: int, block: int,
                   timestamp: int) -> tuple[str, int | None, str | None]:
    code = bytes(w3.eth.get_code(locker.address, block_identifier=block))
    if not code:
        return "unknown", None, "locker_has_no_code"
    code_hash = _hex(w3.keccak(code)).lower()
    if code_hash != locker.expected_code_hash:
        return "unknown", None, "locker_code_hash_mismatch"
    calldata = token_id.to_bytes(32, "big")
    locked_raw = bytes(w3.eth.call({
        "to": locker.address, "data": locker.is_locked_selector + calldata.hex()
    }, block_identifier=block))
    unlock_raw = bytes(w3.eth.call({
        "to": locker.address, "data": locker.unlock_time_selector + calldata.hex()
    }, block_identifier=block))
    if len(locked_raw) < 32 or len(unlock_raw) < 32:
        return "unknown", None, "malformed_locker_response"
    locked = int.from_bytes(locked_raw[-32:], "big")
    unlock_time = int.from_bytes(unlock_raw[-32:], "big")
    if locked not in (0, 1):
        return "unknown", None, "invalid_locker_boolean"
    if locked == 1 and unlock_time > timestamp:
        return "locked", unlock_time, None
    if locked == 1 and unlock_time <= timestamp:
        return "unlocked", unlock_time, None
    # A negative lock flag does not prove that this contract-held NFT is free.
    return "unknown", unlock_time, "locker_did_not_confirm_active_lock"


def fetch_v3_position_snapshot(
    w3,
    manager_address: str,
    from_block: int,
    *,
    to_block: int | None = None,
    chunk_size: int = 2_000,
    lockers: Iterable[LockerConfig] = (),
) -> V3Snapshot:
    if from_block < 0 or chunk_size < 1:
        raise ValueError("Invalid block range or chunk size")
    chain_id = int(w3.eth.chain_id)
    if chain_id != 1:
        raise ValueError(f"Expected Ethereum mainnet chain_id=1, got {chain_id}")
    checksum = w3.to_checksum_address
    manager = checksum(manager_address)
    latest = int(w3.eth.block_number)
    end = latest if to_block is None else int(to_block)
    if end < from_block or end > latest:
        raise ValueError("Invalid snapshot block range")
    block = w3.eth.get_block(end)
    block_hash = _hex(block["hash"])
    timestamp = int(block["timestamp"])
    contract = w3.eth.contract(address=manager, abi=POSITION_MANAGER_ABI)

    # Keep the last Transfer recipient for every minted tokenId. This also
    # identifies burns without treating ownerOf() reverts as successful evidence.
    last_owner: dict[int, str] = {}
    logs = _fetch_logs_adaptive(w3, manager, from_block, end, chunk_size)
    for log in logs:
        topics = log["topics"]
        if len(topics) != 4 or _topic_bytes(topics[0]).hex() != TRANSFER_TOPIC[2:]:
            raise ValueError("Malformed ERC-721 Transfer log")
        sender = _topic_address(topics[1], checksum)
        recipient = _topic_address(topics[2], checksum)
        token_id = int.from_bytes(_topic_bytes(topics[3]), "big")
        if sender.lower() == ZERO:
            last_owner[token_id] = recipient
        elif token_id in last_owner:
            last_owner[token_id] = recipient

    locker_by_address = {item.address.lower(): item for item in lockers}
    rows: list[V3Position] = []
    warnings: list[str] = []
    locked_count = unlocked_count = burned_count = unknown_count = 0
    for token_id, event_owner in sorted(last_owner.items()):
        if event_owner.lower() in {ZERO, DEAD}:
            rows.append(V3Position(token_id, event_owner, "burn", "burned", None,
                                   None, None, None, None, None, None, None, None))
            burned_count += 1
            continue
        owner = checksum(contract.functions.ownerOf(token_id).call(block_identifier=end))
        if owner.lower() != event_owner.lower():
            raise RuntimeError(f"ERC-721 ownerOf/event owner mismatch for tokenId {token_id}")
        position = contract.functions.positions(token_id).call(block_identifier=end)
        code = bytes(w3.eth.get_code(owner, block_identifier=end))
        owner_type = "contract" if code and code != b"\\x00" else "eoa"
        custody = "unlocked" if owner_type == "eoa" else "unknown"
        unlock_timestamp = None
        warning = None
        if owner_type == "contract":
            locker = locker_by_address.get(owner.lower())
            if locker is None:
                warning = "contract_owner_not_in_verified_locker_registry"
            else:
                custody, unlock_timestamp, warning = _verify_locker(
                    w3, locker, token_id, end, timestamp,
                )
        if custody == "locked":
            locked_count += 1
        elif custody == "unlocked":
            unlocked_count += 1
        else:
            unknown_count += 1
        if warning:
            warnings.append(f"token_{token_id}:{warning}")
        rows.append(V3Position(
            token_id, owner, owner_type, custody, unlock_timestamp,
            checksum(position[2]), checksum(position[3]), int(position[4]),
            int(position[5]), int(position[6]), int(position[7]),
            int(position[10]), int(position[11]), warning,
        ))

    final_block = w3.eth.get_block(end)
    stable = _hex(final_block["hash"]) == block_hash
    if not stable:
        warnings.append("snapshot_block_reorged_during_read")
    complete = stable
    if not stable:
        # Keep observed rows for diagnostics, but don't publish custody counts as trusted.
        locked_count = unlocked_count = burned_count = unknown_count = 0
    active_count = sum(1 for row in rows if row.owner_type != "burn")
    if unknown_count:
        warnings.append("one_or_more_positions_have_unknown_custody")
    return V3Snapshot(
        chain_id, manager, from_block, end, block_hash, timestamp,
        len(last_owner), active_count, locked_count, unlocked_count,
        burned_count, unknown_count, complete, tuple(rows),
        tuple(dict.fromkeys(warnings)),
    )


def snapshot_to_dict(snapshot: V3Snapshot) -> dict[str, Any]:
    return asdict(snapshot)
