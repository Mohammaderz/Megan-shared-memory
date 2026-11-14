# Megan Research Priorities — 2026-11

## Purpose and scope

This policy governs the Ethereum Mainnet, observation-only research MVP. It does not authorize wallet connection, private-key handling, transaction signing, automatic buying/selling, or deployment to another chain. Accuracy and evidence quality take priority over speed and alert volume.

## Operating principles

1. **No evidence, no green light.** Missing, stale, contradictory, rate-limited, or failed-source data remains UNKNOWN. Never convert it to SAFE or a positive score.
2. **Safety before momentum.** A token cannot become a high-priority candidate while critical contract, sellability, liquidity-control, or holder-distribution checks are unknown.
3. **Independent confirmation.** Prefer at least two methodologically different sources for critical claims (for example static contract analysis plus transaction simulation, or API data plus direct on-chain verification).
4. **Net outcomes, not attractive screenshots.** Any future strategy evaluation must include gas, pool fees, price impact, slippage, failed transactions, MEV, latency, and exit liquidity.
5. **Reproducibility.** Store timestamp, source, raw response/hash, parser version, and evidence age. Every warning and score must be explainable.
6. **No claims of profitability without testing.** A risk score is not a return forecast. No strategy is promoted based on anecdotal wins or cherry-picked charts.

## Priority queue

### P0 — Correctness and data integrity (active immediately)

- Fix response parsing so Honeypot.is `simulationSuccess` or the mere presence of `buyTax` is never mistaken for a successful buy or sell simulation.
- Keep buy and sell simulation outcomes UNKNOWN unless the provider explicitly supplies those exact outcomes.
- Distinguish pair transaction counts from unique buyers/sellers. DEX Screener buys/sells are not wallet counts.
- Preserve UNKNOWN on source failures; attach source timestamps and errors.
- Add regression tests for these rules before expanding scoring.

### P1 — Security evidence (next integrations)

Use complementary evidence, not a single vendor score:

- **GoPlus Token Security API (Ethereum chain ID 1):** static/heuristic contract and token controls such as honeypot flags, mintability, proxy status, pausing, blacklist controls, ownership changes, and taxes. Treat missing fields as UNKNOWN and independently verify high-impact flags.
- **Honeypot.is:** dynamic buy/sell simulation and tax estimates. Its simulation status is not itself proof that both directions succeeded.
- **Direct Ethereum RPC / verified contract source:** verify owner/admin roles, proxy implementation and upgrade authority, mint/burn controls, blacklist/pause/tax setters, and relevant storage/code paths where feasible.
- **Liquidity and LP ownership:** identify the actual pool and LP/NFT position, lock or burn mechanism, controlling owner, lock expiry, and changes over time. Do not assume that a displayed lock percentage covers all liquidity.
- **Holder and deployer graph:** calculate concentration after excluding verified pool, burn, router, and known infrastructure addresses; trace common funding, same-block entries, deployer retention, and repeated launch-and-dump histories. Label inferred wallet relationships as probable, not proven.

### P1 — Market quality and exit feasibility

- Use GeckoTerminal for new-pool discovery and DEX Screener for pair-level market snapshots, with source freshness checks.
- Add historical OHLCV and swap-level data before any momentum or volume signal is trusted.
- Measure liquidity depth and estimated price impact for realistic order sizes, not just headline TVL.
- Track pool liquidity changes, unique trader counts, buy/sell imbalance, wallet concentration, trade-size concentration, and suspicious repeated/self-funded flows.
- Treat volume/liquidity ratios and transaction counts as anomaly indicators, not proof of organic demand.
- Verify that an exit is feasible at the intended size after fees and slippage.

### P1 — Research and validation

- Build a timestamped cohort of every detected candidate, including rejected candidates, not just winners.
- Record outcomes at fixed horizons (for example 5m, 15m, 1h, 6h, 24h, 7d) and label rugs, dead pools, migrations, and survivorship.
- Use chronological train/validation/test splits and walk-forward evaluation; never leak future data into launch-time features.
- Compare every rule against a simple baseline. Track precision, recall, false-negative rate for dangerous tokens, coverage, and net simulated P&L.
- Paper-trade only after historical validation; keep live execution disabled until a separately reviewed specification and explicit approval exist.

### P2 — Narrative and social signals

- Add only public, permitted, rate-limit-compliant sources with clear provenance.
- Require independent sources and evidence of real participants; do not equate mention count, follower count, influencer posts, or paid promotion with demand.
- Detect copied text, coordinated posting, bot-like account bursts, and sudden narrative decay.
- Never scrape private groups, bypass access controls, or use purchased engagement as a quality signal.

## Tools and sources: order of adoption

| Priority | Tool/source | Intended role | Guardrail |
|---|---|---|---|
| Core | Ethereum RPC provider with reliable logs and tracing | Ground-truth chain events and contract reads | Confirm chain ID, reorg handling, trace coverage and rate limits |
| Core | GeckoTerminal | New-pool discovery and pool snapshots | Discovery feed is not complete chain coverage |
| Core | DEX Screener | Pair metadata, liquidity/volume snapshots | Not unique-wallet analytics or a security audit |
| Core | Honeypot.is | Dynamic sellability/tax simulation | Distinguish simulation status from trade-direction results |
| Next | GoPlus | Independent static/heuristic token-security evidence | Missing fields are UNKNOWN; verify critical flags |
| Next | Etherscan / Sourcify and direct bytecode inspection | Source verification, proxy and admin analysis | Verified source does not prove benign behavior |
| Research | Dune / indexed swap datasets | Cohort studies, historical outcomes, wallet-flow analysis | Check coverage, query definitions and time leakage |
| Later | Public social sources | Narrative corroboration | Provenance, manipulation and access-policy controls |

Do not add paid providers merely because they advertise speed or a high token count. First benchmark coverage, freshness, uptime, field semantics, rate limits, licensing, cost per useful candidate, and incremental value over existing sources.

## Explicitly deprioritized or prohibited

- Blind launch sniping and buying solely because a token is new, trending, or has high short-term volume.
- Treating a third-party risk score, liquidity-lock badge, verified-source badge, or renounced-owner label as a complete safety guarantee.
- Universal fixed thresholds without chain/pool context and out-of-sample calibration.
- Using API outages, missing fields, stale cache, parse errors, or unsupported token types as passing checks.
- Counting buys/sells as unique wallets or assuming many trades mean organic demand.
- Optimizing win rate while ignoring loss size, fees, gas, slippage, failed transactions, MEV, and inability to exit.
- Promoting a strategy from a handful of examples, backtest-only results, cherry-picked tokens, or survivorship-biased leaderboards.
- Connecting a wallet, storing seed phrases/private keys, or enabling unattended execution in this research agent.

## Current implementation gaps to keep visible

The current MVP discovers Ethereum contracts/pools and uses GeckoTerminal, DEX Screener, and Honeypot.is. It does not yet independently verify GoPlus security fields, complete holder distribution, deployer-wallet history/clustering, LP lock ownership/expiry, unique buyers/sellers, full swap history, social evidence, or strategy profitability. These fields must remain UNKNOWN until implemented and tested.

## Promotion gate

A new source or signal becomes an active decision input only after:
1. its schema and semantics are checked against official documentation and live examples;
2. parsing and failure modes have unit tests;
3. timestamps, provenance, and UNKNOWN handling are preserved;
4. it adds measurable value on a chronological holdout cohort;
5. false positives and dangerous false negatives are reviewed.

Until then it may be collected as experimental evidence, but it must not silently raise opportunity scores or lower risk scores.
