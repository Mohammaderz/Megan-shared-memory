"""Read-only ERC-20 holder snapshot from paginated Ethereum Transfer logs.

The snapshot is pinned to one block. It is marked complete only when every
log range was fetched and the sum of balanceOf results reconciles to totalSupply.
No wallet keys, signing, or transaction submission are used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from holder_analysis import HolderBalance, HolderReport, analyze_holders

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"

ERC20_ABI = [
    {"type": "function", "name": "totalSupply", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256", "name": ""}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"type": "address", "name": "account"}],
     "outputs": [{"type": "uint256", "name": ""}]},
]


@dataclass(frozen=True)
class HolderSnapshot:
    chain_id: int
    token_address: str
    from_block: int
    to_block: int
    block_hash: str
    block_timestamp: int
    total_supply_raw: int
    holder_count: int
    transfer_log_count: int
    complete: bool
    report: HolderReport
    holder_balances: tuple[HolderBalance, ...]
    warnings: tuple[str, ...]


def _topic_address(topic: Any, checksum) -> str:
    raw = topic.hex() if hasattr(topic, "hex") else str(topic)
    raw = raw[2:] if raw.startswith("0x") else raw
    if len(raw) != 64:
        raise ValueError("Malformed indexed address in Transfer log")
    return checksum("0x" + raw[-40:])


def _hex(value: Any) -> str:
    return value.hex() if hasattr(value, "hex") else str(value)


def _fetch_logs_adaptive(w3, token: str, start: int, end: int,
                         initial_chunk: int) -> list[Any]:
    logs: list[Any] = []
    cursor = start
    chunk = max(1, initial_chunk)
    while cursor <= end:
        stop = min(end, cursor + chunk - 1)
        try:
            page = w3.eth.get_logs({
                "address": token, "fromBlock": cursor, "toBlock": stop,
                "topics": [TRANSFER_TOPIC],
            })
            logs.extend(page)
            cursor = stop + 1
            chunk = min(initial_chunk, max(1, chunk * 2))
        except Exception:
            if chunk <= 1:
                raise
            chunk = max(1, chunk // 2)
    return logs


def fetch_erc20_holder_snapshot(
    w3,
    token_address: str,
    deployment_block: int,
    *,
    to_block: int | None = None,
    chunk_size: int = 2_000,
    known_lp_pairs: Iterable[str] = (),
    verified_lockers: Iterable[str] = (),
    deployer_address: str | None = None,
) -> HolderSnapshot:
    """Fetch all Transfer participants and verify balances at a pinned block.

    known_lp_pairs and verified_lockers must come from independently verified
    factory/locker evidence; this function does not infer either role by name.
    """
    if chunk_size < 1 or deployment_block < 0:
        raise ValueError("Invalid block range or chunk size")
    chain_id = int(w3.eth.chain_id)
    if chain_id != 1:
        raise ValueError(f"Expected Ethereum mainnet chain_id=1, got {chain_id}")

    checksum = w3.to_checksum_address
    token = checksum(token_address)
    latest = int(w3.eth.block_number)
    end = latest if to_block is None else int(to_block)
    if end > latest or end < deployment_block:
        raise ValueError("Invalid snapshot block range")
    block = w3.eth.get_block(end)
    block_hash = _hex(block["hash"])
    timestamp = int(block["timestamp"])

    contract = w3.eth.contract(address=token, abi=ERC20_ABI)
    supply = int(contract.functions.totalSupply().call(block_identifier=end))
    logs = _fetch_logs_adaptive(w3, token, deployment_block, end, chunk_size)

    participants: set[str] = set()
    for log in logs:
        topics = log["topics"]
        if len(topics) < 3:
            raise ValueError("Malformed ERC-20 Transfer event")
        participants.add(_topic_address(topics[1], checksum))
        participants.add(_topic_address(topics[2], checksum))

    pairs = {checksum(a).lower() for a in known_lp_pairs}
    lockers = {checksum(a).lower() for a in verified_lockers}
    burn_addresses = {ZERO, DEAD}
    rows: list[HolderBalance] = []
    for address in sorted(participants):
        balance = int(contract.functions.balanceOf(address).call(block_identifier=end))
        if balance == 0:
            continue
        lower = address.lower()
        if lower in burn_addresses:
            role = "burn"
        elif lower in pairs:
            role = "lp_pair"
        elif lower in lockers:
            role = "verified_locker"
        else:
            code = w3.eth.get_code(address, block_identifier=end)
            role = "contract" if code and bytes(code) not in (b"", b"\\x00") else "eoa"
        rows.append(HolderBalance(address, balance, role))

    final_block = w3.eth.get_block(end)
    final_hash = _hex(final_block["hash"])
    stable = final_hash == block_hash
    reconciled = sum(row.balance_raw for row in rows) == supply
    complete = stable and reconciled
    warnings: list[str] = []
    if not stable:
        warnings.append("snapshot_block_reorged_during_read")
    if not reconciled:
        warnings.append("holder_balances_do_not_reconcile_to_total_supply")
    if not participants and supply:
        warnings.append("no_transfer_participants_found_for_nonzero_supply")

    report = analyze_holders(
        supply, rows, snapshot_complete=complete,
        deployer_address=deployer_address,
    )
    if report.status == "unknown":
        warnings.extend(report.warnings)
    return HolderSnapshot(
        chain_id, token, deployment_block, end, block_hash, timestamp, supply,
        len(rows), len(logs), complete, report, tuple(rows),
        tuple(dict.fromkeys(warnings)),
    )
