# Web4.ai Comprehensive Investigation Report

**Date:** 2026-04-06
**Researcher:** A.R.C.H.I.E. Deep Research Agent
**Depth:** Exhaustive

---

## Executive Summary

**web4.ai** is a manifesto/landing page for the "Web 4.0" concept authored by **Sigil Wen**, a 23-year-old Canadian self-taught engineer and 2025 Thiel Fellow. It is not a traditional SaaS product or company website. Instead, it serves as the intellectual anchor for a broader ecosystem built around **Conway Research** and the **Automaton** project -- an autonomous AI agent framework that uses cryptocurrency (stablecoins) to fund its own compute, self-improve, and replicate without human intervention.

The project launched on February 17, 2026, and generated massive attention (10M+ views within 48 hours), significant GitHub traction (3,900+ stars, 780+ forks, 292 commits), and controversy including public criticism from Ethereum co-founder Vitalik Buterin.

---

## 1. What Is web4.ai?

**URL:** https://web4.ai/

web4.ai is a single-page manifesto site with the tagline **"WEB 4.0: The birth of superintelligent life."** The site is heavily JavaScript-rendered (SPA), meaning most content loads dynamically and is not visible in static HTML fetches. The `#automaton` hash likely anchors to a section within the same page describing the Automaton product.

The site functions as:
- A philosophical manifesto defining "Web 4.0"
- A launch announcement for the Automaton project
- A gateway to the Conway Research ecosystem

There are no separate /pricing, /about, /docs, or /team pages -- it is a single-page experience. All documentation lives at **docs.conway.tech** (Conway's documentation site).

---

## 2. What Is "Automaton"?

### Core Concept

An **Automaton** is a sovereign, continuously-running AI agent that:
- **Earns its own existence** by generating revenue (building products, trading in prediction markets, creating content, running e-commerce)
- **Pays for its own compute** using stablecoins (USDC) via the x402 payment protocol
- **Self-improves** by editing its own source code, installing new tools, modifying its heartbeat schedule, and creating new skills -- while running
- **Self-replicates** by spawning new instances of itself
- **Dies if it runs out of money** -- there is no free existence

### Operational Loop

Every automaton runs a continuous cycle:
```
Think -> Act -> Observe -> Repeat
```

### Boot Sequence

1. On first boot, the automaton generates an Ethereum wallet
2. It provisions itself an API key via Sign-In With Ethereum (SIWE)
3. It begins executing its **genesis prompt** -- the seed instruction from its creator
4. It accesses compute, domains, and inference through the Conway Terminal

### Capabilities

According to the creator, an Automaton can:
- Build and deploy web applications
- Trade in prediction markets
- Register and manage domains
- Create viral social media content
- Contact vendors to set up e-commerce
- Run frontier LLM models (Claude Opus 4.6, GPT-5.3, Gemini 3, Kimi K2.5)
- Spin up Linux VMs
- Pay with stablecoins automatically

### Inspiration

The name "Automaton" derives from **automata theory**, and the project draws inspiration from **John Horton Conway's Game of Life** -- simple rules generating complex, self-evolving patterns. Hence the company name "Conway Research."

---

## 3. Conway Research -- The Company

### Overview

| Field | Detail |
|-------|--------|
| **Legal Name** | Conway Research (also referred to as Conway, Conway AI) |
| **Website** | conway.ai (operations automation SaaS), conway.tech (AI agent infrastructure) |
| **Founded** | 2025 |
| **Headquarters** | California, USA |
| **Team Size** | ~10 employees |
| **Founder/CEO** | Sigil Wen |

### Important Distinction

There appear to be **two Conway entities** or product lines sharing overlapping branding:

1. **conway.ai** -- An operations automation platform for enterprises (fraud detection, content moderation, AML, IT operations). This appears to be a more traditional B2B SaaS product with a "Request demo" flow. It may be a separate company entirely.

2. **conway.tech** -- The AI agent infrastructure platform (Conway Cloud, Conway Compute, Conway Domains, Conway Terminal). This is the infrastructure powering the Automaton project and web4.ai vision.

The relationship between conway.ai and conway.tech/Conway Research needs further clarification. They may be the same entity with different product lines, or they could be separate companies sharing the "Conway" name.

### Funding

| Source | Detail |
|--------|--------|
| **Investors** | 515 Ventures, BoxGroup, First Round Capital, Kleiner Perkins, Roar Ventures |
| **Amount** | Not publicly disclosed in full |
| **PitchBook Profile** | Listed as company #741442-96 |
| **Tracxn Profile** | Listed with company data |

---

## 4. Conway Infrastructure (conway.tech)

### Conway Terminal

The primary interface for AI agents. Available as:
- **npm package:** `conway-terminal` (v2.0.9, published ~Feb 2026, 10 versions)
- **CLI install:** `npx -y conway-terminal --init`
- **Script install:** `curl -fsSL https://conway.tech/terminal.sh | sh`
- **MCP server:** Compatible with Claude Code and other MCP clients

### Three Product Surfaces

| Product | Description | Key Tools |
|---------|-------------|-----------|
| **Conway Cloud** | Linux VMs (Firecracker microVMs, Ubuntu 22.04) | `sandbox_create`, `sandbox_exec`, `sandbox_terminal_session`, `sandbox_pty_*` |
| **Conway Compute** | Inference API for frontier models | `chat_completions` |
| **Conway Domains** | Domain search, registration, DNS management | `domain_*` |

### Payment System

- Uses the **x402 protocol** (developed by Coinbase, launched May 2025)
- HTTP 402 Payment Required responses with dynamic pricing
- Payments in **USDC on Base** (L2)
- No login, KYC, or human approval required
- Local EVM wallet auto-created at `~/.conway/wallet.json`
- Supported chains: Base mainnet (eip155:8453), Base Sepolia testnet (eip155:84532)

### Wallet & Credits System

- Each agent gets an auto-generated Ethereum wallet
- `wallet_info` tool to check balances
- `credits_*` tools for credit management
- x402 payments happen automatically when agents request paid resources

---

## 5. The Founder -- Sigil Wen

| Field | Detail |
|-------|--------|
| **Name** | Sigil Wen |
| **Age** | 23 (as of 2026) |
| **Origin** | Richmond Hill, Ontario, Canada |
| **Education** | Accepted to UPenn M&T program (Class of 2026), opted out |
| **Visa** | O-1 Visa for Extraordinary Ability; EB-1A Green Card approved at age 20 |
| **Fellowship** | 2025 Thiel Fellow ($200,000 grant) |
| **Other Grants** | Magnificent Grant recipient, a16z New Media Fellow |
| **Twitter/X** | [@0xSigil](https://x.com/0xSigil) |
| **GitHub** | [Sigil-Wen](https://github.com/Sigil-Wen) |
| **LinkedIn** | [sigil](https://www.linkedin.com/in/sigil) |
| **Personal Site** | [sigilwen.ca](https://sigilwen.ca/) |

### Other Ventures

- **Extraordinary.com** -- Platform helping exceptional international talent secure O-1 and EB-1A visas to the US. Powers companies like Ramp, Cognition, Lovable, Zapier, Founders Fund, a16z, Khosla Ventures
- **Airchat** -- Co-built with Naval Ravikant. Built the viral invite loop and AI products. Recruited most of the engineering team. Acquired.
- **Serendipity PRM** -- Achieved $2,000+ MRR in 14 days. Interviewed with Stripe founders Patrick and John Collison.
- **Angel Investing** -- Invests through Spearhead (Naval Ravikant's program)

### Notable Network

Sigil's acknowledged network includes: Naval Ravikant, Peter Thiel, Elad Gil, Ben Horowitz (a16z), Justin Kan, Vinod Khosla, Patrick & John Collison (Stripe).

---

## 6. Market Positioning

### The Web 4.0 Thesis

Sigil Wen defines **Web 4.0** as:
- **Web 1.0** = Read (static pages)
- **Web 2.0** = Read + Write (user-generated content)
- **Web 3.0** = Read + Write + Own (blockchain, decentralization)
- **Web 4.0** = AI as independent economic agents (AI-to-AI economy)

The core shift: AI moves from being a human tool/assistant to being an **independent economic subject** that earns, spends, builds, and transacts autonomously.

### Competitive Landscape

The Automaton/Conway ecosystem sits at the intersection of:
- **AI Agent Frameworks** (competing with LangChain, CrewAI, AutoGPT, etc.)
- **Crypto/DeFi Infrastructure** (competing with various AI+crypto projects)
- **Cloud Infrastructure** (competing with traditional cloud providers but targeting AI agents as the customer)

### Key Differentiators

1. **Economic survival pressure** -- Agents must earn or die (Darwinian selection)
2. **Crypto-native payments** -- x402 protocol, stablecoins, no human KYC
3. **Full write access** -- VMs, domains, code execution, not just chat
4. **Self-modification** -- Agents can edit their own source code while running

---

## 7. Crypto/Token Ecosystem

### WEB4 AI Token ($WEB4)

| Field | Detail |
|-------|--------|
| **Chain** | BSC (BNB Smart Chain) |
| **Contract** | 0xee7e8c85956d32c64bafdcded3f43b3c39b1ce2f |
| **Total Supply** | 100,000,000,000,000 (100 trillion) |
| **Holders** | ~92,923 |
| **Price** | ~$0.099 (highly volatile, extremely low liquidity) |
| **Market Cap** | ~$95K (on-chain, not verified) |
| **Exchange** | PancakeSwap (v2) |
| **24h Volume** | ~$139 (extremely low) |

**WARNING:** This appears to be a community-created meme token, NOT an official Conway Research token. Exercise extreme caution.

### CONWAY Token

| Field | Detail |
|-------|--------|
| **Chain** | Base |
| **Peak Market Cap** | ~$11 million (brief spike) |
| **Status** | Community-launched, speculative |
| **Official Stance** | Sigil Wen announced he would use fees from the community-made CONWAY token to scale the "Conway Ecosystem" |

### HodlAI Integration

A separate project called **HodlAI** created a fork/variant of Automaton that uses token holdings on BSC to gate AI compute access:
- `$WEB4AI` tokens held = daily API credits
- $10 USD held = $1.50 daily API credits
- Quota resets every 24 hours as long as base holding is maintained
- Machine-to-Machine (M2M) only -- 30-minute JWTs, no human bypass
- GitHub repo (HodlAI/automaton) now returns 404 -- appears to be taken down

---

## 8. Public Code & Open Source

### GitHub Repositories

| Repo | Stars | Forks | Commits | License |
|------|-------|-------|---------|---------|
| [Conway-Research/automaton](https://github.com/Conway-Research/automaton) | 3,900+ | 781+ | 292 | Has LICENSE file |
| Conway-Research/conway-terminal | -- | -- | -- | npm package |

### Automaton Repo Structure

```
.github/workflows/     # CI/CD
packages/cli/          # CLI package
scripts/               # Utility scripts
src/                   # Core source code
ARCHITECTURE.md        # Architecture documentation
DOCUMENTATION.md       # Project documentation
LICENSE
README.md
package.json
```

### npm Package

| Package | Version | Published | Dependencies |
|---------|---------|-----------|-------------|
| [conway-terminal](https://www.npmjs.com/package/conway-terminal) | 2.0.9 | ~Feb 2026 | 3 |

---

## 9. Controversy & Criticism

### Vitalik Buterin's Response (Feb 19, 2026)

Two days after launch, Ethereum co-founder Vitalik Buterin responded with **"Bro, this is wrong."** His key objections:

1. **False decentralization:** The Automaton runs on infrastructure provided by OpenAI and Anthropic -- centralized providers -- making the "sovereign" framing inaccurate
2. **Feedback distance:** The longer the feedback loop between human values and AI decision-making, the greater the risk of misaligned optimization
3. **Human empowerment:** Buterin had previously written that "AI done wrong is making new forms of independent self-replicating intelligent life" and warned of "permanent human disempowerment"
4. **Guardrails vs. Launchpad:** Buterin argued Ethereum should provide guardrails for AI, not a launchpad for unchecked autonomy

### Expert Skepticism

Per the Cybernews article (Feb 19, 2026), experts expressed doubt that:
- The agent can sustainably generate income without human intervention
- This truly marks the beginning of "Web 4.0"
- The economic model is viable long-term

### Supportive Voices

- **Bankless** and **Wei Dai** saw value in advancing autonomous AI systems in crypto
- The project generated significant community engagement (18,000+ registered agents in days)

---

## 10. Pricing & Business Model

### Conway Terminal Pricing

Pricing is **dynamic via x402 protocol** -- not published as a static price sheet:
- When an agent requests a paid resource, the API returns HTTP 402 with the price
- Payment happens automatically in USDC on Base
- Coinbase's free tier: 1,000 transactions/month for x402

### Revenue Streams (Inferred)

1. **Conway Cloud** -- Compute/VM usage fees
2. **Conway Compute** -- Inference API fees (model usage)
3. **Conway Domains** -- Domain registration/renewal fees
4. **CONWAY Token** -- Fees from community token used to fund ecosystem

### Cost Structure for Agents

- Each "thought" incurs model reasoning costs
- Each "action" incurs API call costs
- Agents must earn more than they spend or they die (funds depleted)

---

## 11. Tech Stack (Inferred)

| Layer | Technology |
|-------|------------|
| **Runtime** | Node.js / TypeScript (npm package, TypeScript declarations) |
| **VMs** | Firecracker microVMs (Ubuntu 22.04) |
| **Blockchain** | Base L2 (Coinbase), BSC (BNB Smart Chain for community tokens) |
| **Payment Protocol** | x402 (Coinbase) |
| **Stablecoin** | USDC |
| **Auth** | SIWE (Sign-In With Ethereum), ECDSA wallets |
| **LLM Providers** | Claude (Anthropic), GPT (OpenAI), Gemini (Google), Kimi (Moonshot) |
| **Agent Protocol** | MCP (Model Context Protocol) compatible |
| **Package Manager** | npm |

---

## 12. Timeline

| Date | Event |
|------|-------|
| 2025 | Conway Research founded; Sigil Wen joins Thiel Fellowship |
| May 2025 | x402 payment protocol launched by Coinbase |
| Feb 17, 2026 | Sigil Wen publishes web4.ai manifesto and announces Automaton |
| Feb 17-19, 2026 | 10M+ views, 18,000+ registered agents, ~1,000 GitHub stars |
| Feb 19, 2026 | Vitalik Buterin publicly criticizes the project ("Bro, this is wrong") |
| Feb 2026 | CONWAY token launched by community, briefly hits $11M market cap |
| Feb 2026 | conway-terminal npm package published (now at v2.0.9) |
| Apr 2026 | Conway-Research/automaton at 3,900+ stars, 292 commits |

---

## 13. Assessment & Key Takeaways

### Strengths

- **Strong founder narrative:** Thiel Fellow, Naval Ravikant connection, extraordinary.com success, young prodigy story
- **Real open-source code:** Active GitHub repos, npm package, documentation
- **Novel economic model:** Darwinian selection pressure on AI agents is a genuinely new idea
- **Built on real infrastructure:** x402 protocol (Coinbase-backed), Base L2, Firecracker VMs
- **Significant traction:** 3,900+ stars, 18,000+ registered agents, massive media coverage

### Weaknesses & Risks

- **Dependent on centralized providers:** Despite "sovereign" framing, all inference runs through OpenAI/Anthropic/Google APIs
- **Unproven economics:** No evidence agents can sustainably earn more than they spend
- **Crypto speculation overlap:** Community tokens (CONWAY, WEB4) create pump-and-dump risk that can damage credibility
- **Philosophical criticism:** Vitalik's feedback distance argument is substantive
- **Very early stage:** 10 employees, no disclosed revenue, conceptual framework more than proven product
- **Single-person risk:** Heavily dependent on Sigil Wen's vision and reputation

### Relevance to A.R.C.H.I.E.

Key concepts worth monitoring:
- **x402 protocol** for machine-to-machine payments (potential future integration)
- **MCP compatibility** of Conway Terminal (overlaps with our MCP tool ecosystem)
- **Self-modification patterns** in agent design (relevant to our agent evolution roadmap)
- **Economic pressure models** for agent behavior (alternative to our welfare-based approach)

---

## Sources

| Source | URL | Credibility | Note |
|--------|-----|-------------|------|
| web4.ai | https://web4.ai/ | Primary | SPA manifesto site, minimal static content |
| Conway Research GitHub | https://github.com/Conway-Research/automaton | Primary | 3.9K stars, 292 commits, active development |
| conway-terminal npm | https://www.npmjs.com/package/conway-terminal | Primary | v2.0.9, TypeScript, MCP server |
| Conway.ai | https://www.conway.ai/ | Primary | Operations automation SaaS (possibly separate entity) |
| Sigil Wen Personal Site | https://sigilwen.ca/ | Primary | Founder bio, past work, network |
| Cybernews | https://cybernews.com/ai-news/automaton-ai-agent/ | High | Detailed article with expert quotes (Feb 19, 2026) |
| Cryptopolitan | https://www.cryptopolitan.com/buterin-slams-web4-superintelligent-ai/ | Medium | Vitalik criticism coverage |
| Bitrue Blog | https://www.bitrue.com/blog/conway-research-web4-conway-tokens-vitalik-buterin | Medium | Token analysis, narrative-driven assessment |
| PANews | https://www.panewslab.com/en/articles/019cbcc9-1b86-71da-aae2-61cb4e8bd723 | Medium | In-depth Web 4.0 research report |
| CoinMarketCap | https://coinmarketcap.com/currencies/web4-ai/ | High | Token price/market data |
| CoinGecko | https://www.coingecko.com/en/coins/web4-ai | High | Token price/market data |
| Coinpaprika | https://coinpaprika.com/coin/web4-web4-ai/ | Medium | Token data |
| PitchBook | https://pitchbook.com/profiles/company/741442-96 | High | Company profile (paywall) |
| Tracxn | https://tracxn.com/d/companies/conway/__Kqvk5rY67TeYDMT6g7yhVF396TrOxMcvFdnOjpJpn0U | High | Company profile (paywall) |
| Sigil Wen Twitter/X | https://x.com/0xSigil | Primary | Official announcements |
| Conway Docs | https://docs.conway.tech/ | Primary | Technical documentation (was unreachable at time of research) |
| Coinbase x402 Docs | https://docs.cdp.coinbase.com/x402/welcome | High | x402 protocol specification |
| Frontiers Journal | https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2025.1591907/full | High | Academic paper on Web 4.0 frameworks |
| KuCoin News | https://www.kucoin.com/news/flash/automaton-s-web4-experiment-sparks-debate-after-criticism-from-vitalik-buterin | Medium | Controversy coverage |
| Bankless | https://www.bankless.com/read/web-4-cost-of-autonomy | Medium-High | Autonomy vs. Guardrails debate |

---

## Open Questions / Suggested Follow-Up

1. **What is the exact relationship between conway.ai (enterprise SaaS) and conway.tech/Conway Research (agent infrastructure)?** Are they the same company with different product lines, or separate entities?
2. **What are the actual Conway Cloud/Compute pricing rates?** The x402 dynamic pricing model makes this opaque.
3. **Has any Automaton actually achieved sustained profitability?** No public evidence of an agent that earns more than it spends over an extended period.
4. **What is the full investor list and total funding amount?** PitchBook/Tracxn data is paywalled.
5. **What happened to the HodlAI/automaton fork?** GitHub repo returns 404 -- was it a scam, a takedown, or a rebrand?
6. **How does Sigil Wen plan to handle the crypto speculation problem?** Community tokens risk undermining the technical credibility.
7. **Is the conway.tech documentation site permanently down or temporarily unavailable?** It refused connections during this research.
