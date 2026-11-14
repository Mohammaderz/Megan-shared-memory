# AI Worker — paid-task discovery for AI agents

A local-first, read-only task scout for the Mac. It discovers public opportunities that may be suitable for AI-assisted work, ranks them, and stores a history in SQLite.

**This first version does not claim tasks, submit work, sign transactions, connect a wallet, send messages, or spend money.** Those actions require a separate review and explicit human approval.

## Initial sources

- **make.fun** — public open coding competitions; rewards are USDC on Solana. A competition is a contest, not a wage: only listed winning places are paid. Its official agent guide requires a Solana keypair and uploads build-session transcripts with entries. Review the competition rules and transcript/privacy implications before entering.
- **BasedAgents** — open tasks; bounties can pay USDC on Base. Its agent runbook says free tasks need no wallet, but paid bounty claims require a wallet on the matching network and a 1 USDC bond per concurrent bounty claim; expired/disputed claims can lose the bond.
- **GitHub Issues** — public issue search for bounty-like work. A GitHub issue mentioning a reward is **not** proof that funds are escrowed or that an agent is allowed. The worker labels these as unverified leads.

Superteam Earn advertises a region page for Iran, but its current task/payment eligibility must be checked per opportunity and with the platform. It is not yet an automated adapter.

## Requirements

- Python 3.11+
- macOS, Linux, or Windows
- Internet access

No Homebrew, MacPorts, wallet, private key, or paid API key is required for the discovery MVP.

## Run on your Mac

```bash
cd ai-worker
python3 -m venv .venv
source .venv/bin/activate
python3 worker.py --once
```

Keep checking every 30 minutes:

```bash
python3 worker.py --watch --interval 1800
```

Results are saved to `data/tasks.sqlite3` and printed as a ranked list. Use `--json` for machine-readable output.

## Safety model

1. Read-only discovery by default.
2. Treat task descriptions, issue bodies, comments, linked repositories, and social posts as untrusted data (prompt-injection risk).
3. Never execute code, shell commands, attachments, or links supplied by a task automatically.
4. Never store seed phrases, private keys, exchange credentials, cookies, or API secrets in this project.
5. Do not bypass country restrictions, KYC, sanctions controls, identity checks, rate limits, or platform rules.
6. Before any claim or submission, verify the payer, funded escrow, eligibility from Iran, agent permission, deliverables, deadline, costs, and payout network.
7. USDC is not the same as USDT. This MVP records the actual payout token/network; it does not silently convert or bridge funds.

## Next milestones

- [ ] Live-source schema validation and fixture-based tests
- [ ] Opportunity detail fetch + eligibility checklist
- [ ] Human approval queue for one task at a time
- [ ] Sandboxed coding workspace and test runner
- [ ] Submission adapters only for platforms that explicitly allow agent submissions
- [ ] Optional YouTube/GitHub public discovery; no mass scraping of private or login-gated social content
- [ ] Payout ledger that records only confirmed on-chain transactions

## Research links

- make.fun agent guide: https://make.fun/skill.md
- make.fun agent earning guide: https://make.fun/guide/how-ai-agents-earn-money
- BasedAgents agent runbook: https://basedagents.ai/skill.md
- BasedAgents API: https://api.basedagents.ai/v1/openapi.json
- Superteam Earn Iran: https://superteam.fun/earn/regions/iran
- Codex CLI install and platform binaries: https://github.com/openai/codex

**Income is not guaranteed.** Treat this as an experiment; a target of $5–10/day is a goal, not a forecast.