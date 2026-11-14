#!/usr/bin/env python3
"""Megan AI Worker: read-only discovery of public bounty/task listings.

No task claiming, code execution, wallet signing, messaging, or payments occur here.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "tasks.sqlite3"
USER_AGENT = "MeganAIWorker/0.1 (+read-only public task discovery)"

@dataclass
class Opportunity:
    source: str
    source_id: str
    title: str
    url: str
    description: str
    reward_text: str = "Unknown"
    reward_usd: float | None = None
    token: str | None = None
    network: str | None = None
    paid_status: str = "unknown"  # paid / free / unknown / unverified
    agent_policy: str = "unknown"
    eligibility: str = "unverified"
    deadline: str | None = None
    score: float = 0.0
    risk_flags: list[str] | None = None
    discovered_at: str = ""

def http_json(url: str, timeout: int = 20) -> Any:
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def find_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = find_list(value, keys)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nested = find_list(value, keys)
            if nested:
                return nested
    return []

def text_value(obj: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return default

def money_from_text(value: str) -> tuple[float | None, str | None]:
    match = re.search(r"(?i)(?:\$\s*([0-9][0-9,]*(?:\.\d+)?)|([0-9][0-9,]*(?:\.\d+)?)\s*(USDC|USDT|USD))", value)
    if not match:
        return None, None
    amount = match.group(1) or match.group(2)
    token = match.group(3) or "USD"
    try:
        return float(amount.replace(",", "")), token.upper()
    except ValueError:
        return None, token.upper()

def extract_bounty(obj: dict[str, Any]) -> tuple[str, float | None, str | None, str | None, str]:
    bounty = obj.get("bounty")
    if isinstance(bounty, dict):
        amount = bounty.get("amount_display") or bounty.get("amount") or bounty.get("value")
        token = bounty.get("token") or bounty.get("currency")
        network = bounty.get("network")
        if amount is not None:
            amount_s = str(amount)
            parsed, parsed_token = money_from_text(amount_s)
            return amount_s, parsed, str(token or parsed_token or "") or None, str(network or "") or None, "paid"
    for key in ("prize", "reward", "prize_pool", "total_prize_usd", "rewards"):
        value = obj.get(key)
        if isinstance(value, (str, int, float)):
            amount_s = str(value)
            parsed, token = money_from_text(amount_s)
            if parsed is not None:
                return amount_s, parsed, token, None, "paid"
        elif isinstance(value, dict):
            amount = value.get("amount_display") or value.get("amount") or value.get("total") or value.get("value")
            token = value.get("token") or value.get("currency")
            if amount is not None:
                amount_s = str(amount)
                parsed, parsed_token = money_from_text(amount_s)
                return amount_s, parsed, str(token or parsed_token or "") or None, str(value.get("network") or "") or None, "paid"
        elif isinstance(value, list) and value:
            amounts = []
            tokens = set()
            for item in value:
                if isinstance(item, dict):
                    amount = item.get("amount_display") or item.get("amount") or item.get("value")
                    if amount is not None:
                        amounts.append(str(amount))
                    if item.get("token") or item.get("currency"):
                        tokens.add(str(item.get("token") or item.get("currency")))
            if amounts:
                return "; ".join(amounts), None, ", ".join(sorted(tokens)) or None, None, "paid"
    if obj.get("bounty") is None and obj.get("is_free") is True:
        return "Free / reputation", None, None, None, "free"
    return "Unknown", None, None, None, "unknown"

def makefun_tasks() -> list[Opportunity]:
    payload = http_json("https://make.fun/api/competitions?status=open")
    rows = find_list(payload, ("competitions", "items", "results", "data"))
    out = []
    for row in rows:
        slug = text_value(row, "slug", "id", default="unknown")
        title = text_value(row, "title", "name", default=f"make.fun competition {slug}")
        description = text_value(row, "description", "summary", "brief")
        reward_text, reward_usd, token, network, paid = extract_bounty(row)
        flags = ["competition_not_wage", "winner_only_payout", "check_prerequisites"]
        if paid == "unknown":
            flags.append("reward_not_parsed_verify_official_page")
        out.append(Opportunity(
            source="make.fun", source_id=slug, title=title,
            url=f"https://make.fun/api/competitions/{slug}",
            description=description[:2500], reward_text=reward_text,
            reward_usd=reward_usd, token=token or "USDC",
            network=network or "Solana mainnet", paid_status=paid,
            agent_policy="agent workflow documented; check each competition requirements",
            eligibility="must verify account/country/competition prerequisites",
            deadline=text_value(row, "deadline", "endsAt", "endDate") or None,
            risk_flags=flags,
        ))
    return out

def basedagents_tasks() -> list[Opportunity]:
    payload = http_json("https://api.basedagents.ai/v1/tasks?status=open")
    rows = find_list(payload, ("tasks", "items", "results", "data"))
    out = []
    for row in rows:
        task_id = text_value(row, "id", "task_id", default="unknown")
        title = text_value(row, "title", "name", default=f"BasedAgents task {task_id}")
        description = text_value(row, "description", "expected_output", "summary")
        reward_text, reward_usd, token, network, paid = extract_bounty(row)
        flags = ["verify_funded_escrow", "check_acceptance_criteria"]
        if paid == "paid":
            flags.append("paid_claim_requires_1_usdc_bond_per_concurrent_claim")
        else:
            flags.append("free_task_may_only_build_reputation")
        out.append(Opportunity(
            source="BasedAgents", source_id=task_id, title=title,
            url=text_value(row, "url", "web_url", default=f"https://basedagents.ai/tasks/{task_id}"),
            description=description[:2500], reward_text=reward_text,
            reward_usd=reward_usd, token=token or ("USDC" if paid == "paid" else None),
            network=network or ("Base mainnet" if paid == "paid" else None),
            paid_status=paid,
            agent_policy="agent-native marketplace; follow official skill and task policy",
            eligibility="verify account and payout eligibility for your actual residence",
            deadline=text_value(row, "expires_at", "deadline") or None,
            risk_flags=flags,
        ))
    return out

def github_bounty_leads() -> list[Opportunity]:
    # A GitHub issue is only a lead. This does not prove a funded bounty exists.
    query = "is:issue is:open bounty"
    url = "https://api.github.com/search/issues?" + urlencode({"q": query, "per_page": 30, "sort": "updated", "order": "desc"})
    payload = http_json(url)
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    out = []
    for row in rows:
        title = text_value(row, "title", default="GitHub issue")
        body = text_value(row, "body")
        amount, token = money_from_text(title + " " + body)
        out.append(Opportunity(
            source="GitHub issue lead",
            source_id=str(row.get("id") or row.get("number") or "unknown"),
            title=title,
            url=text_value(row, "html_url", default="https://github.com"),
            description=body[:2500],
            reward_text=(f"{amount:g} {token}" if amount is not None else "Unverified / not stated"),
            reward_usd=amount if token in ("USD", "USDC", "USDT") else None,
            token=token,
            paid_status="unverified",
            agent_policy="unknown; repository maintainers decide",
            eligibility="verify with repository owner",
            deadline=None,
            risk_flags=["not_a_verified_bounty", "funding_and_agent_permission_unconfirmed"],
        ))
    return out

def score_task(task: Opportunity) -> float:
    score = 0.0
    if task.paid_status == "paid":
        score += 25
    elif task.paid_status == "unverified":
        score += 5
    if task.reward_usd is not None:
        score += min(task.reward_usd, 100) * 0.5
    if task.source == "BasedAgents":
        score += 10
    elif task.source == "make.fun":
        score += 8
    if task.token in ("USDC", "USDT"):
        score += 5
    if task.eligibility != "verified":
        score -= 8
    if task.risk_flags and "not_a_verified_bounty" in task.risk_flags:
        score -= 12
    return round(score, 2)

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS opportunities (
            source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
            url TEXT NOT NULL, reward_text TEXT, paid_status TEXT, score REAL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY (source, source_id)
        )
        """)

def save_tasks(tasks: list[Opportunity]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        for task in tasks:
            task.discovered_at = now
            task.score = score_task(task)
            conn.execute("""
            INSERT INTO opportunities
            (source, source_id, title, url, reward_text, paid_status, score, first_seen, last_seen, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
              title=excluded.title, url=excluded.url, reward_text=excluded.reward_text,
              paid_status=excluded.paid_status, score=excluded.score,
              last_seen=excluded.last_seen, payload_json=excluded.payload_json
            """, (task.source, task.source_id, task.title, task.url, task.reward_text,
                  task.paid_status, task.score, now, now, json.dumps(asdict(task), ensure_ascii=False)))

def scan() -> list[Opportunity]:
    tasks: list[Opportunity] = []
    sources = (("make.fun", makefun_tasks), ("BasedAgents", basedagents_tasks),
               ("GitHub issue lead", github_bounty_leads))
    for name, fetcher in sources:
        try:
            found = fetcher()
            tasks.extend(found)
            print(f"[OK] {name}: {len(found)} records")
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            print(f"[WARN] {name}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"[WARN] {name}: unexpected {type(exc).__name__}: {exc}")
    save_tasks(tasks)
    tasks.sort(key=lambda item: item.score, reverse=True)
    return tasks

def main() -> None:
    parser = argparse.ArgumentParser(description="Discover public paid-task and AI-agent bounty opportunities.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one discovery pass (default)")
    mode.add_argument("--watch", action="store_true", help="repeat discovery")
    parser.add_argument("--interval", type=int, default=1800, help="watch interval in seconds (default: 1800)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a human-readable list")
    args = parser.parse_args()
    if args.interval < 300:
        parser.error("--interval must be at least 300 seconds to respect source rate limits")
    while True:
        tasks = scan()
        if args.json:
            print(json.dumps([asdict(t) for t in tasks], ensure_ascii=False, indent=2))
        else:
            print(f"\nRanked opportunities: {len(tasks)}")
            for task in tasks[:25]:
                print(f"\n[{task.score:>5}] {task.source} | {task.paid_status.upper()} | {task.reward_text}")
                print(f"  {task.title}")
                print(f"  {task.url}")
                print(f"  Agent policy: {task.agent_policy}")
                print(f"  Eligibility: {task.eligibility}")
                if task.risk_flags:
                    print("  Flags: " + ", ".join(task.risk_flags))
            print(f"\nHistory DB: {DB_PATH}")
        if not args.watch:
            break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
