"""Public, read-only market data adapters. No wallet or signing functionality."""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from typing import Any

UA = "Megan-Ethereum-Research/0.1 (+read-only)"
class SourceError(RuntimeError): pass

def get_json(url: str, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200: raise SourceError(f"HTTP {response.status}: {url}")
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise SourceError(f"Source request failed ({url}): {exc}") from exc

def geckoterminal_new_pools() -> list[dict[str, Any]]:
    """Fetch current Ethereum new pools; API is paginated and rate-limited."""
    payload = get_json("https://api.geckoterminal.com/api/v2/networks/eth/new_pools")
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    out = []
    for row in rows:
        attrs = row.get("attributes") or {}
        rel = row.get("relationships") or {}
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id")
        quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id")
        out.append({
            "source": "geckoterminal", "pool_address": attrs.get("address"),
            "pool_name": attrs.get("name"), "created_at": attrs.get("pool_created_at"),
            "reserve_usd": attrs.get("reserve_in_usd"), "base_token_id": base,
            "quote_token_id": quote, "raw": attrs,
        })
    return out

def dexscreener_token_pairs(address: str) -> list[dict[str, Any]]:
    address = address.strip()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError("Expected an Ethereum token contract address")
    payload = get_json("https://api.dexscreener.com/latest/dex/tokens/" + urllib.parse.quote(address))
    pairs = payload.get("pairs") or []
    return [p for p in pairs if (p.get("chainId") == "ethereum")]

def honeypot_check(address: str) -> dict[str, Any]:
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError("Expected an Ethereum token contract address")
    url = "https://api.honeypot.is/v2/IsHoneypot?" + urllib.parse.urlencode({"address": address, "chainID": 1})
    return get_json(url)

def extract_pool_metrics(pair: dict[str, Any]) -> dict[str, Any]:
    liq = pair.get("liquidity") or {}
    txns = pair.get("txns") or {}
    h1 = txns.get("h1") or {}
    return {
        "dex_id": pair.get("dexId"), "pair_address": pair.get("pairAddress"),
        "url": pair.get("url"), "price_usd": pair.get("priceUsd"),
        "liquidity_usd": _number(liq.get("usd")),
        "volume_h1_usd": _number((pair.get("volume") or {}).get("h1")),
        "buys_h1": _number(h1.get("buys")), "sells_h1": _number(h1.get("sells")),
        "price_change_h1_pct": _number((pair.get("priceChange") or {}).get("h1")),
        "fdv": _number(pair.get("fdv")), "market_cap": _number(pair.get("marketCap")),
    }

def _number(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None
