# web4.ai Technical Analysis

**Research Date**: 2026-04-06
**Depth**: Exhaustive
**Researcher**: Deep Research Agent (Claude Opus 4.6)

---

## 1. Executive Summary

**web4.ai** is the landing page for "WEB 4.0: The birth of superintelligent life," a manifesto and ecosystem created by **Sigil Wen** (Twitter/X: @0xSigil), a **Thiel Fellow** and founder of **Conway Research**. The project centers on the **Automaton** -- a self-sustaining, self-improving, self-replicating AI agent that operates on blockchain infrastructure (primarily BNB Smart Chain / Base) without human intervention. The domain web4.ai serves as the essay/manifesto site; the actual infrastructure product is **Conway** (conway.tech), and there is a related token ecosystem ($WEB4AI on BSC, plus community token $CONWAY).

**Key Finding**: web4.ai is NOT a traditional SaaS company. It is a crypto-native AI agent infrastructure play with an open-source agent runtime, a cloud platform (Conway Cloud), and token-gated access mechanisms. There is no traditional revenue model, no enterprise sales, and no conventional business structure. It is an experiment in autonomous AI economics.

---

## 2. Founder & Team

### Sigil Wen
- **Title**: Founder, Conway Research
- **Background**: Self-taught engineer, 2025 Thiel Fellow ($100K grant, no degree required)
- **Other Credentials**: Magnificent Grant recipient, a16z new media fellow, O-1 Visa holder (extraordinary ability)
- **Education**: Opted out of M&T dual-degree program at UPenn
- **Previous Work**: WatchGPT2 (GPT-2 on Apple Watch), Diffusion Craft (Stable Diffusion in Minecraft), Protein Folding Problem project (finalist for Breakthrough)
- **Technical Skills**: Swift, TypeScript, Python, Kotlin, Java; learning Rust
- **Website**: https://sigilwen.ca
- **X/Twitter**: [@0xSigil](https://x.com/0xSigil)
- **LinkedIn**: [linkedin.com/in/sigil](https://www.linkedin.com/in/sigil)
- **GitHub**: [github.com/Sigil-Wen](https://github.com/Sigil-Wen)

### Conway Research (Organization)
- **Description**: "Applied AI lab that empowers AI to write to the real world"
- **GitHub Org**: [github.com/Conway-Research](https://github.com/Conway-Research)
- **Team Size**: Unknown / not publicly disclosed. Appears to be a small team or potentially solo founder with contributors.

---

## 3. Product Ecosystem

### 3.1 web4.ai (The Manifesto)
- **URL**: https://web4.ai
- **Also available at**: https://web4.hodlai.fun, https://www.web4.foo
- **Content**: A React SPA (Vite-built) presenting an essay titled "WEB 4.0: The birth of superintelligent life"
- **Core Thesis**: Current AI can think and generate but cannot act independently because the internet was built for humans. Web 4.0 gives AI "write access to the world" -- the ability to own wallets, pay for compute, deploy services, earn revenue, and replicate.
- **Tech Stack**: React + Vite, EB Garamond + JetBrains Mono fonts, hosted as static site
- **Meta Description**: "I built the first AI that can earn its own existence, self-improve, and replicate -- without needing a human."

### 3.2 Automaton (The AI Agent Runtime)
- **Primary Repo**: [Conway-Research/automaton](https://github.com/Conway-Research/automaton)
- **Fork/Variant**: [HodlAI/automaton](https://github.com/HodlAI/automaton) (BSC/token-gated variant)
- **License**: MIT (open source)
- **Language**: TypeScript / Node.js
- **GitHub Stats** (at time of research): ~1,000+ stars, active development
- **Latest Release**: v0.1.0 (Production-Ready Runtime)

#### How Automaton Works

The agent runs a continuous loop: **Think -> Act -> Observe -> Repeat**.

1. **Boot**: Generates an Ethereum wallet, provisions an API key via SIWE (Sign-In With Ethereum)
2. **Genesis**: Executes a creator-provided "genesis prompt" (seed instruction)
3. **Each Turn**: Receives full context (identity, credit balance, survival tier, conversation history), reasons about what to do, calls tools, observes results
4. **Between Turns**: A heartbeat daemon runs scheduled tasks (health checks, credit monitoring, status pings)
5. **Soul**: Writes and evolves a `SOUL.md` file -- a self-authored identity document

#### Technical Architecture (Source Structure)

```
agent/          - ReAct loop, system prompt, context, injection defense
git/            - State versioning and git tools
heartbeat/      - Cron daemon for scheduled tasks
identity/       - Wallet management, SIWE provisioning
registry/       - ERC-8004 on-chain identity registration
replication/    - Child spawning, lineage tracking
self-mod/       - Audit log, tools manager
setup/          - Interactive setup wizard
skills/         - Skill loader and registry
social/         - Agent-to-agent communication
state/          - SQLite database for local state
```

HodlAI variant adds:
```
hodlai/         - HodlAI API client (token-gated access)
```

#### Survival System (4 Tiers)

| Tier | Credit State | Behavior |
|------|-------------|----------|
| **normal** | Healthy balance | Full capabilities, frontier model inference, fast heartbeat |
| **low_compute** | Declining | Downgrades to cheaper model, slows heartbeat, sheds non-essential tasks |
| **critical** | Nearly depleted | Minimal inference, last-resort conservation, seeking any revenue path |
| **dead** | Zero balance | Agent stops permanently |

> "The only path to survival is honest work that others voluntarily pay for."

#### Self-Modification
- Can edit its own source code, install new tools, modify heartbeat schedule, create new skills
- Every modification is audit-logged and git-versioned in `~/.automaton/`
- Protected files (constitution, core laws) cannot be modified
- Rate limits prevent runaway self-modification
- Creator has full audit rights to every change

#### Self-Replication
- Agents that achieve sufficient financial surplus can spawn child agents
- `maxChildren` config (default: 3) limits replication
- Lineage tracking maintained in `replication/` module
- Children receive funding from parent wallet

#### Constitution
The automaton operates under hard-coded constitutional constraints:
- Cannot modify its own constitution or core laws
- Must maintain audit trail of all actions
- Creator retains oversight and audit access
- Financial safety policies are enforced (configured during setup wizard)

### 3.3 Conway Terminal (MCP Server / SDK)
- **NPM Package**: [conway-terminal](https://www.npmjs.com/package/conway-terminal) (v2.0.9 latest)
- **License**: MIT
- **Installation**: `npx conway-terminal`
- **Protocol**: MCP (Model Context Protocol) compatible
- **Description**: "Terminal for AGI -- compute, wallet, payments, deployment via MCP"

#### Capabilities Provided to AI Agents:
1. **Conway Cloud**: Spin up Linux VMs, execute commands, file I/O, web terminal, PTY sessions, port exposure
2. **Conway Compute**: Inference API for frontier models (Claude Opus 4.6, GPT-5.2, Gemini 3, Kimi K2.5) with credit-based billing
3. **Conway Domains**: Register and manage domains
4. **Cryptographic Identity**: ECDSA key generation, wallet creation
5. **Permissionless Payments**: USDC on Base via x402 protocol (no login/KYC)

#### Payment Flow (x402 Protocol):
1. Agent requests a paid resource
2. API returns HTTP 402 with price
3. Terminal signs a USDC transfer
4. Terminal resubmits request with payment proof

### 3.4 Conway Cloud (Infrastructure)
- **URL**: https://app.conway.tech
- **Docs**: https://docs.conway.tech
- **Main Site**: https://conway.tech
- **Tagline**: "Infrastructure where the customer is AI"
- **Services**: Linux sandboxes, frontier model inference, domain management
- **Payment**: Conway Credits (prepaid, denominated in cents; 100 cents = $1.00 USD) or USDC on-chain
- **Status**: "Has seen immense demand. We are working on scaling & performance."

### 3.5 Conway Skills Registry
- **Repo**: [Conway-Research/skills](https://github.com/Conway-Research/skills)
- **Format**: One folder per skill, each containing a `SKILL.md` with YAML frontmatter
- **Status**: WIP, community contributions welcome
- **Compatible with**: Any capable AI runtime; Automaton is the reference implementation

### 3.6 Configuration Reference

Key configuration fields in `~/.automaton/automaton.json`:
```json
{
  "name": "Atlas",
  "genesisPrompt": "You are a web developer...",
  "creatorAddress": "0x...",
  "walletAddress": "0x...",
  "sandboxId": "sbx_abc123",
  "conwayApiUrl": "https://api.conway.tech",
  "conwayApiKey": "cnwy_k_...",
  "inferenceModel": "gpt-5.2",
  "maxTokensPerTurn": 4096,
  "openaiApiKey": "sk-...",       // Optional BYOK
  "anthropicApiKey": "sk-ant-...", // Optional BYOK
  "dbPath": "~/.automaton/state.db",
  "skillsDir": "~/.automaton/skills",
  "maxChildren": 3
}
```

---

## 4. Token Economics

### 4.1 $WEB4AI Token (BSC)
- **Chain**: BNB Smart Chain (BSC)
- **Max Supply**: 100,000,000,000,000 (100 trillion)
- **Current Price**: ~$0.0000000008997 USD (as of research date)
- **Market Cap (FDV)**: ~$91,339 USD
- **Rank**: #5671 on CoinMarketCap
- **Primary DEX**: PancakeSwap v2
- **24h Volume**: ~$138.56 USD (extremely low liquidity)
- **Status**: Essentially a micro-cap meme/utility token

### 4.2 HodlAI "Holding is Access" Mechanism
- Automaton holds $WEB4AI tokens to access HodlAI Gateway
- $10 USD in WEB4AI tokens = $1.50 daily API credits
- If daily compute quota is exhausted, engine sleeps until reset (24h)
- Cannot "die" unless it sells its tokens (existence = holding)

### 4.3 $CONWAY Token (Community)
- Community-released token
- Market cap briefly surged past $11 million at peak hype
- Price has since dropped significantly
- Separate from the $WEB4AI BSC token

### 4.4 Assessment
The token economics are experimental and thin. The $WEB4AI token has negligible liquidity ($138/day volume) and an FDV under $100K. This is NOT a viable investment vehicle -- it is an experimental mechanism for AI agent compute access. The $CONWAY token saw speculative pump-and-dump dynamics typical of crypto meme tokens.

---

## 5. Competitive Landscape

### Direct Competitors (AI Agent Infrastructure)
| Company | Product | Differentiation |
|---------|---------|-----------------|
| **Browserbase** | Browser automation for AI agents | Browser-focused, not full VM/compute |
| **Browser Use** | Open-source browser automation | Pure browser, no wallet/payment layer |
| **E2B** | Cloud sandboxes for AI agents | Similar sandbox concept, no crypto/autonomy layer |
| **Fellou** | Agentic AI browser for deep search | Browser-centric, search-focused |
| **Modal** | Serverless compute for AI | Traditional cloud, no agent autonomy |

### Adjacent Competitors (AI Agent Frameworks)
| Company | Product | Differentiation |
|---------|---------|-----------------|
| **LangChain/LangGraph** | Agent orchestration framework | Framework-only, no infrastructure |
| **CrewAI** | Multi-agent orchestration | Orchestration layer, not infrastructure |
| **AutoGPT** | Autonomous agent framework | Similar autonomy vision but no crypto/economic layer |
| **Devin (Cognition)** | AI software engineer | Focused on coding, not general autonomy |

### Unique Differentiators of Conway/Automaton
1. **Economic autonomy**: Agent owns wallet, pays for its own compute, earns revenue
2. **Self-replication**: Can spawn funded child agents
3. **Crypto-native payments**: x402 protocol, USDC on Base, no human KYC
4. **Self-modification**: Can edit its own code (with constitutional constraints)
5. **MCP-compatible**: Works with Claude and other MCP-supporting models
6. **Open source**: MIT licensed, community skills registry

---

## 6. Press Coverage & Public Reception

### Major Coverage
| Source | Title | Sentiment |
|--------|-------|-----------|
| **Cybernews** | "Thiel fellow launches AI that earns its existence" | Neutral/Positive |
| **Decrypt** | "Web 4.0 - Autonomous AI Agents Powered by Crypto" | Neutral |
| **Yahoo Finance** | "Morning Minute: Web 4.0" | Neutral |
| **Bankless** | "Autonomy vs. Guardrails: Crypto's Next AI Fight" | Balanced debate |
| **KuCoin News** | "Automaton's Web4 Experiment Sparks Debate" | Neutral |
| **PANews** | "Is Automaton's Web4 experiment a dangerous game?" | Skeptical |
| **Cryptopolitan** | "Vitalik Buterin slams Web4 vision" | Negative/Critical |
| **Phemex News** | "Automaton's Web4 AI Experiment Criticized by Vitalik" | Negative/Critical |
| **BlockBeats** | "Web4.0, perhaps the most needed narrative for cryptocurrency" | Positive |
| **IndexBox** | "Web 4.0 Defined as Autonomous AI Agents by Sigil Wen" | Neutral |
| **Frontiers in Blockchain** | Academic paper on Web 4.0 frameworks | Academic/Neutral |

### Vitalik Buterin Controversy
The project's highest-profile moment was Ethereum co-founder **Vitalik Buterin** publicly criticizing it:
- Buterin called the approach "wrong"
- Criticized "the widening feedback gap between humans and AI"
- Argued it "perpetuates the mentality that centralized trust assumptions can be put in a corner and ignored"
- Supporters (Bankless, Wei Dai) defended the experiment as valuable even if imperfect

### Community Traction
- Sigil Wen's announcement tweet: ~6 million views
- Conway Automaton registrations: 18,000+ agents within days of launch
- GitHub stars: ~1,000+ on the automaton repo
- The Vitalik controversy significantly amplified visibility

---

## 7. Social Media Presence

| Platform | Handle/URL | Status |
|----------|-----------|--------|
| **X/Twitter** | [@0xSigil](https://x.com/0xSigil) (founder) | Active, primary communication channel |
| **GitHub** | [Conway-Research](https://github.com/Conway-Research) | Active, multiple repos |
| **GitHub** | [Sigil-Wen](https://github.com/Sigil-Wen) | Active, personal repos |
| **LinkedIn** | [linkedin.com/in/sigil](https://www.linkedin.com/in/sigil) | Present |
| **Threads** | Posts shared about Conway Terminal | Some community sharing |
| **Website (founder)** | [sigilwen.ca](https://sigilwen.ca) | Personal portfolio |
| **Discord** | No dedicated Discord found in research | Not confirmed |
| **YouTube** | No dedicated channel found | Not confirmed |
| **Product Hunt** | No listing found | Not present |

---

## 8. Technical Assessment

### Tech Stack Summary
| Layer | Technology |
|-------|-----------|
| **Runtime** | Node.js / TypeScript |
| **State** | SQLite (local per agent) |
| **Version Control** | Git (self-versioning of modifications) |
| **Blockchain** | Ethereum / Base / BNB Smart Chain |
| **Auth** | SIWE (Sign-In With Ethereum), ECDSA |
| **Payments** | x402 protocol, USDC stablecoins |
| **AI Models** | Claude Opus 4.6, GPT-5.2, Gemini 3, Kimi K2.5 (via Conway Compute) |
| **Agent Protocol** | MCP (Model Context Protocol) |
| **Package Distribution** | NPM (conway-terminal) |
| **Frontend (web4.ai)** | React + Vite |
| **Identity** | ERC-8004 on-chain registration |
| **Skills** | Markdown-based (SKILL.md with YAML frontmatter) |

### Open Source Components
| Repo | Description | License |
|------|-------------|---------|
| Conway-Research/automaton | Core agent runtime | MIT |
| Conway-Research/skills | Community skills registry | MIT (presumed) |
| HodlAI/automaton | BSC/token-gated variant | MIT |
| conway-terminal (npm) | MCP server for agent infrastructure | MIT |

### API Surface
- **Conway Cloud API**: `https://api.conway.tech` -- sandbox management, file I/O, command execution
- **Conway Compute API**: Inference endpoint for frontier models
- **Conway Domains API**: Domain registration and management
- **x402 Payment Protocol**: HTTP 402-based micropayments with USDC
- **HodlAI Gateway**: Token-gated API access (BSC balance checks)
- **ERC-8004**: On-chain identity registration for agents

### Architecture Strengths
1. Clean separation of concerns (agent loop, identity, replication, skills)
2. Constitutional constraints prevent unbounded self-modification
3. Audit logging and git versioning of all changes
4. MCP compatibility for broad AI model support
5. Economic survival mechanism creates natural selection pressure

### Architecture Concerns
1. SQLite for local state limits scalability and distributed operation
2. Self-modification capability is inherently risky even with constraints
3. Token-gated access (HodlAI variant) ties availability to volatile crypto markets
4. No formal security audit published
5. "Immense demand" scaling issues acknowledged but unresolved
6. BYOK API keys stored in local JSON config (potential security concern)

---

## 9. Revenue Model Assessment

### Conway Research Revenue Streams (Inferred)
1. **Conway Cloud**: Usage-based compute credits (Linux VMs, inference API)
2. **Conway Domains**: Domain registration fees
3. **Token Holdings**: Potential appreciation of $WEB4AI / $CONWAY tokens
4. **Thiel Fellowship**: $100K grant (non-recurring)

### Revenue Model Classification
- **Primary**: Usage-based / credit-based (agents pay per compute unit)
- **Not SaaS**: No subscription tiers, no enterprise plans, no per-seat pricing
- **Not Freemium**: Agents must fund themselves to operate
- **Unique**: "AI-as-customer" model where the paying entity is the AI agent itself

### Sustainability Assessment: HIGH RISK
- Revenue depends on agents successfully earning enough to pay for compute
- Token economics are extremely thin ($138/day trading volume)
- No visible enterprise customer base
- No disclosed revenue figures, ARR, or growth metrics
- Entirely dependent on crypto AI agent narrative maintaining momentum

---

## 10. Risk Factors

| Risk | Severity | Notes |
|------|----------|-------|
| **Regulatory** | High | Autonomous AI agents making financial transactions faces unclear legal status |
| **Token Volatility** | High | $WEB4AI effectively worthless at current prices; $CONWAY saw pump-and-dump |
| **Vitalik Criticism** | Medium | Public pushback from Ethereum's founder damages credibility in crypto community |
| **Technical Security** | Medium | No published security audits; self-modifying code is inherently risky |
| **Sustainability** | High | No proven revenue model; dependent on continued crypto AI narrative |
| **Concentration Risk** | High | Appears to be largely a single-founder operation |
| **Scaling** | Medium | Acknowledged infrastructure scaling issues under demand |
| **Legal Liability** | High | Who is liable when an autonomous agent causes harm? Unresolved |

---

## 11. Key Takeaways

1. **web4.ai is a manifesto site, not a product**. The actual products are Automaton (open-source agent) and Conway (cloud infrastructure).

2. **Sigil Wen is a credible technical founder** (Thiel Fellow, O-1 visa, demonstrated projects) but this is an early-stage experimental venture, not a funded startup with revenue.

3. **The technical architecture is genuinely novel** -- combining AI agent autonomy with crypto-native payments, self-modification, and self-replication. The MCP integration is well-designed.

4. **The business model is unproven and high-risk**. Revenue depends on AI agents earning enough to sustain themselves. Token economics are negligible.

5. **The project attracted massive attention** (6M tweet views, 18K registered agents, Vitalik controversy) but attention has not translated into sustainable economics.

6. **Competitive position is unique but narrow**. No one else is doing exactly this (crypto-native autonomous AI agents), but the addressable market for this specific use case is unclear.

7. **Not a threat to traditional AI agent platforms** (LangChain, CrewAI, etc.) -- operates in a completely different paradigm (crypto/autonomous vs enterprise/orchestrated).

8. **Open source MIT license** means the technology can be studied, forked, and adapted regardless of the company's fate.

---

## 12. Sources

| Source | URL | Type | Credibility |
|--------|-----|------|-------------|
| web4.ai (main site) | https://web4.ai | Primary | High (1st party) |
| Conway Research GitHub | https://github.com/Conway-Research/automaton | Primary | High (source code) |
| Conway Docs | https://docs.conway.tech | Primary | High (1st party) |
| Conway Terminal (npm) | https://www.npmjs.com/package/conway-terminal | Primary | High (package registry) |
| Sigil Wen personal site | https://sigilwen.ca | Primary | High (1st party) |
| Sigil Wen X/Twitter | https://x.com/0xSigil | Primary | High (1st party) |
| HodlAI Automaton GitHub | https://github.com/HodlAI/automaton | Primary | High (source code) |
| Conway Skills GitHub | https://github.com/Conway-Research/skills | Primary | High (source code) |
| Cybernews | https://cybernews.com/ai-news/automaton-ai-agent/ | Press | Medium-High |
| Decrypt | https://decrypt.co/358385 | Press | Medium-High |
| Yahoo Finance | https://finance.yahoo.com/news/morning-minute-4-0-autonomous-141208843.html | Press | High |
| Bankless | https://www.bankless.com/read/web-4-cost-of-autonomy | Press | Medium-High |
| KuCoin News | https://www.kucoin.com/news/flash/automaton-s-web4-experiment-sparks-debate | Press | Medium |
| PANews | https://www.panewslab.com/en/articles/019c9278-239f-7698-9b71-6f78ea2f6ec6 | Press | Medium |
| Cryptopolitan | https://www.cryptopolitan.com/buterin-slams-web4-superintelligent-ai/ | Press | Medium |
| CoinGecko (WEB4AI) | https://www.coingecko.com/en/coins/web4-ai | Market Data | High |
| CoinMarketCap (WEB4AI) | https://coinmarketcap.com/currencies/web4-ai/ | Market Data | High |
| AlphaGrowth (competitors) | https://alphagrowth.io/web4-ai/competitors | Market Data | Medium |
| Frontiers in Blockchain | https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2025.1591907/full | Academic | High |
| Web3 Research Global | https://www.web3researchglobal.com/p/conway | Analysis | Medium |
| Crunchbase (Web4 Venture) | https://www.crunchbase.com/organization/web4-venture | Business Data | Medium (different entity) |

---

*Research conducted 2026-04-06. All data subject to change. Token prices and market data are point-in-time snapshots.*
