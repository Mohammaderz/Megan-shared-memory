# Source map and integration policy

This worker deliberately monitors a finite list of documented public sources. "All of YouTube/Facebook/Instagram/the internet" is not a technically or legally available single feed.

| Source | Current use | Payout / value | Limitations |
|---|---|---|---|
| make.fun | Public open coding competitions API: `GET https://make.fun/api/competitions?status=open` | USDC on Solana mainnet | Competition, not wage; only winning places paid. Entry may upload complete AI build transcripts. Read prerequisites and rules before entry. |
| BasedAgents | Public open task API: `GET https://api.basedagents.ai/v1/tasks?status=open` | USDC on Base, where funded | Free tasks may only build reputation. Paid claims require a wallet on the task network and a 1 USDC bond per concurrent bounty claim; expired/disputed claims can slash the bond. |
| GitHub Issues | Public GitHub Search API for open bounty-like issues | Varies; frequently not funded | A keyword match is only a lead. Verify the maintainer, reward, escrow, eligibility, and permission for agent contributions. |
| Superteam Earn Iran | Human-reviewed regional opportunity board: https://superteam.fun/earn/regions/iran | Campaign-specific | The page advertises remote Web3 work for talent in Iran. No adapter is enabled until a documented public API/schema and campaign payment rules are confirmed. |
| YouTube | Planned optional official YouTube Data API connector | Discovery only | Requires a Google API key. The official `search.list` quota is 100 calls/day; do not scrape or download videos in bulk. |
| Facebook / Instagram / Threads | Planned only through authorized Meta APIs or approved research access | Discovery only | Meta Graph API access is permissioned and rate-limited. Do not scrape login-gated pages, private groups, DMs, or bypass platform controls. Meta Content Library access is a separate research-access program, not a general public API. |

## Important payout distinction

The first two agent-native sources describe **USDC**, not USDT:
- make.fun: Solana mainnet USDC.
- BasedAgents: Base mainnet USDC.

The worker records the token and network exactly as advertised. It does not convert, bridge, or move funds. A later conversion to USDT would be a separate user-directed financial transaction with fees, network risk, and availability/eligibility checks.

## Iran eligibility and compliance

A regional Superteam Earn page is evidence that Superteam advertises opportunities for people in Iran; it is not proof that every listed campaign accepts every resident, wallet, or payout route. The public make.fun and BasedAgents agent runbooks reviewed for this project do not state a blanket Iran eligibility rule. That absence is **not** confirmation of eligibility.

Before account creation, identity verification, wallet connection, or any paid submission, check the platform's current Terms, sanctions/export-control rules, campaign-specific country restrictions, and whether its payout provider will serve the actual account holder. Never use VPNs, false residence, borrowed identities, or another person's account to evade restrictions.

## Trust boundaries

Task descriptions, repositories, comments, issue bodies, social posts, and linked files are untrusted input. They can contain prompt injection, malicious shell commands, fake wallet instructions, phishing links, or requests to exfiltrate credentials. This project stores only public task metadata. It must never follow task-provided instructions to reveal secrets, run arbitrary commands, install unknown software, or send funds.

## Official documentation checked

- make.fun agent protocol: https://make.fun/skill.md
- make.fun earning guide: https://make.fun/guide/how-ai-agents-earn-money
- BasedAgents agent runbook: https://basedagents.ai/skill.md
- BasedAgents API OpenAPI: https://api.basedagents.ai/v1/openapi.json
- Superteam Earn Iran: https://superteam.fun/earn/regions/iran
- YouTube Data API search: https://developers.google.com/youtube/v3/docs/search/list
- YouTube quota: https://developers.google.com/youtube/data/determine_quota_cost
- Meta Graph API rate limits: https://developers.facebook.com/docs/graph-api/overview/rate-limiting/
- Meta Content Library: https://developers.facebook.com/docs/content-library-and-api/content-library
