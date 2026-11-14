"""Normalize Ethereum internal contract-creation traces from Geth and Erigon."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

class TraceRPCError(RuntimeError):
    """A configured RPC endpoint rejected or failed a tracing request."""

@dataclass(frozen=True)
class ContractCreation:
    address: str
    creator: str
    tx_hash: str
    creation_method: str
    provider: str

@dataclass(frozen=True)
class TraceBatch:
    provider: str
    creations: tuple[ContractCreation, ...]

def _address(value: Any) -> str | None:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        return None
    return value.lower()

def _walk_geth_frame(frame: Any, tx_hash: str, provider: str, output: list[ContractCreation]) -> None:
    if not isinstance(frame, dict):
        return
    kind = str(frame.get("type", "")).upper()
    if kind in {"CREATE", "CREATE2"} and not frame.get("error"):
        address = _address(frame.get("to") or frame.get("createdAddress"))
        creator = _address(frame.get("from"))
        if address and creator and tx_hash:
            output.append(ContractCreation(address, creator, tx_hash, kind.lower(), provider))
    children = frame.get("calls", [])
    if isinstance(children, list):
        for child in children:
            _walk_geth_frame(child, tx_hash, provider, output)

def normalize_geth_block_trace(response: Any) -> TraceBatch:
    """Normalize debug_traceBlockByNumber(callTracer) output."""
    if not isinstance(response, list):
        raise ValueError("Geth block trace must be an array")
    found: list[ContractCreation] = []
    for tx_trace in response:
        if not isinstance(tx_trace, dict):
            continue
        tx_hash = tx_trace.get("txHash") or tx_trace.get("transactionHash")
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
            continue
        _walk_geth_frame(tx_trace.get("result"), tx_hash.lower(), "geth_callTracer", found)
    return TraceBatch("geth_callTracer", tuple(found))

def normalize_erigon_block_trace(response: Any) -> TraceBatch:
    """Normalize Erigon/OpenEthereum-compatible flat trace_block output."""
    if not isinstance(response, list):
        raise ValueError("Erigon trace_block result must be an array")
    found: list[ContractCreation] = []
    for item in response:
        if not isinstance(item, dict) or str(item.get("type", "")).lower() != "create":
            continue
        if item.get("error"):
            continue
        action = item.get("action") or {}
        result = item.get("result") or {}
        address = _address(result.get("address"))
        creator = _address(action.get("from"))
        tx_hash = item.get("transactionHash")
        method = str(action.get("creationMethod", "create")).lower()
        if method not in {"create", "create2"}:
            method = "create"
        if address and creator and isinstance(tx_hash, str) and tx_hash.startswith("0x"):
            found.append(ContractCreation(address, creator, tx_hash.lower(), method, "erigon_trace"))
    return TraceBatch("erigon_trace", tuple(found))

class TraceDiscovery:
    """Optional block trace adapter. Auto mode tries Erigon, then Geth callTracer."""
    def __init__(self, web3: Any, mode: str = "auto"):
        mode = mode.strip().lower()
        if mode not in {"auto", "erigon", "geth", "off"}:
            raise ValueError("TRACE_MODE must be auto, erigon, geth, or off")
        self.web3 = web3
        self.mode = mode

    def _request(self, method: str, params: list[Any]) -> Any:
        response = self.web3.provider.make_request(method, params)
        if not isinstance(response, dict):
            raise TraceRPCError(f"{method} returned a non-object response")
        if response.get("error"):
            raise TraceRPCError(f"{method}: {response['error']}")
        if "result" not in response:
            raise TraceRPCError(f"{method}: response has no result")
        return response["result"]

    def trace_block(self, block_number: int) -> TraceBatch:
        if self.mode == "off":
            return TraceBatch("disabled", ())
        block_hex = hex(block_number)
        attempts: list[str] = []
        modes = ("erigon", "geth") if self.mode == "auto" else (self.mode,)
        for mode in modes:
            try:
                if mode == "erigon":
                    return normalize_erigon_block_trace(self._request("trace_block", [block_hex]))
                raw = self._request("debug_traceBlockByNumber", [block_hex, {"tracer": "callTracer"}])
                return normalize_geth_block_trace(raw)
            except (TraceRPCError, ValueError, TypeError) as exc:
                attempts.append(str(exc))
        raise TraceRPCError("No supported block trace API succeeded: " + " | ".join(attempts))
