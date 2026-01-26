# ARCHIE POOL - Complete Developer Documentation

**Project:** Archie Pool Mining Platform
**Company:** Kytran Empowerment Inc.
**Location:** Montreal, Quebec, Canada
**Infrastructure:** TELUS Fiber Business (940/940 Mbps)
**Host Server:** 192.168.1.250 (kyt-emp-host)
**Target Date:** Q1 2026

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Database Schema](#database-schema)
4. [Service Components](#service-components)
5. [Management Interface](#management-interface)
6. [API Documentation](#api-documentation)
7. [Deployment Instructions](#deployment-instructions)
8. [Game Integration](#game-integration)
9. [Revenue Model](#revenue-model)
10. [Troubleshooting](#troubleshooting)

---

## Executive Summary

### Project Overview

Archie Pool is an intelligent, AI-powered cryptocurrency mining pool that allows miners to:
- Mine Ravencoin (KawPow algorithm) and Beam (BeamHash III)
- Receive payouts in **any supported cryptocurrency** (BTC, ETH, XMR, LTC, etc.)
- Convert earnings to game credits for integration with Kytran's gaming ecosystem
- Benefit from Archie AI optimization and support

### Core Value Propositions

1. **Flexible Payouts** - Mine one coin, get paid in another (like Unmineable)
2. **Lower Fees** - 0.5% pool + 1% conversion = 1.5% total (vs 2-3% competitors)
3. **AI Optimization** - Archie monitors, optimizes, and provides 24/7 support
4. **Game Integration** - Unique feature connecting mining to gaming economy
5. **Enterprise Infrastructure** - Running on TELUS Business fiber (940 Mbps up/down)

### Competitive Advantages

| Feature | Unmineable | NiceHash | **Archie Pool** |
|---------|-----------|----------|-----------------|
| Flexible payouts | Yes | No | **Yes** |
| Total fees | 2% | 2-3% | **1.5%** |
| AI optimization | No | No | **Yes** |
| Game integration | No | No | **Yes** |
| Telegram support | No | No | **Yes (Archie bot)** |
| Community marketplace | No | No | **Yes (Kytran)** |

### Technical Stack

```
Backend:
├─ NOMP (Node Open Mining Portal) - Stratum server
├─ Ravencoin Core - Blockchain node
├─ PostgreSQL 15 - Primary database
├─ Redis 7 - Cache & queue system
├─ Python 3.11 - AI services & automation
├─ Node.js 18 - Pool software & APIs
└─ Nginx Proxy Manager - Reverse proxy & SSL

Frontend:
├─ React 18 - Management dashboard
├─ Tailwind CSS - Styling
├─ Recharts - Data visualization
└─ WebSockets - Real-time updates

Infrastructure:
├─ Docker & Docker Compose - Containerization
├─ Portainer - Container management
├─ Existing Archie AI system - Intelligence layer
└─ n8n - Workflow automation (already deployed)
```

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                           INTERNET                               │
│                        (Global Miners)                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
         [Miners]      [Web Users]   [API Consumers]
              │              │              │
              └──────────────┼──────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              NGINX PROXY MANAGER (Existing)                      │
│  - SSL Termination (Let's Encrypt)                              │
│  - DDoS Protection                                               │
│  - Rate Limiting                                                 │
│  - Domain Routing                                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌─────────────┐
      │   Stratum    │ │   Web    │ │    Pool     │
      │   Servers    │ │Dashboard │ │    API      │
      │ :3333/:3334  │ │  :8084   │ │   :5000     │
      └──────┬───────┘ └─────┬────┘ └──────┬──────┘
             │               │             │
             └───────────────┼─────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       REDIS CLUSTER                              │
│  - Share queue (high-throughput writes)                         │
│  - Worker sessions (fast lookups)                               │
│  - Real-time statistics (in-memory)                             │
│  - Pub/Sub for events                                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌─────────────┐
      │    Share     │ │  Payout  │ │ Conversion  │
      │  Validator   │ │  Manager │ │   Engine    │
      │  (Python)    │ │ (Python) │ │  (Python)   │
      └──────┬───────┘ └─────┬────┘ └──────┬──────┘
             │               │             │
             └───────────────┼─────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   POSTGRESQL DATABASE                            │
│  - Workers & Accounts                                           │
│  - Shares & Blocks                                              │
│  - Payouts & Conversions                                        │
│  - Game Economy Data                                            │
│  - Audit Logs                                                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌─────────────┐
      │  Ravencoin   │ │   Beam   │ │   Monero    │
      │    Node      │ │   Node   │ │    Node     │
      │  (KawPow)    │ │(BeamHash)│ │  (RandomX)  │
      └──────────────┘ └──────────┘ └─────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ARCHIE AI LAYER                             │
│  ┌───────────────────────────────────────────────────────┐      │
│  │     Intelligence Services (Connect to existing Archie) │      │
│  │  - Performance monitoring & optimization               │      │
│  │  - Difficulty adjustment AI                            │      │
│  │  - Conversion timing predictions                       │      │
│  │  - Fraud & anomaly detection                          │      │
│  │  - Telegram bot integration                           │      │
│  │  - Profitability analysis                             │      │
│  └───────────────────────────────────────────────────────┘      │
│  ┌───────────────────────────────────────────────────────┐      │
│  │           n8n Workflows (Already deployed)             │      │
│  │  - Block found notifications                          │      │
│  │  - Miner alerts                                       │      │
│  │  - Daily reports                                      │      │
│  │  - Payment confirmations                              │      │
│  └───────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
1. MINER CONNECTS
   Miner → Nginx → Stratum Server
   ├─ Authenticate wallet address
   ├─ Load difficulty settings from Redis
   └─ Send mining job from blockchain node

2. SHARE SUBMISSION
   Miner → Stratum → Redis Queue
   ├─ Validate share (async)
   ├─ Update worker stats in Redis
   ├─ Store in PostgreSQL (batched)
   └─ If block found → Alert Archie AI

3. BLOCK FOUND
   Stratum → PostgreSQL + Archie AI
   ├─ Record block details
   ├─ Calculate PPLNS payouts
   ├─ Queue conversions (if needed)
   ├─ Send Telegram notification
   └─ Update web dashboard (WebSocket)

4. PAYOUT PROCESSING
   Payout Manager (Cron)
   ├─ Check confirmed blocks
   ├─ Calculate miner shares
   ├─ Check payout preferences
   ├─ If native coin → Direct payout
   ├─ If different coin → Queue conversion
   └─ Send to blockchain node

5. CONVERSION PROCESSING
   Conversion Engine
   ├─ Get exchange rate (CoinGecko/Changelly)
   ├─ Execute swap (Changelly API)
   ├─ Confirm transaction
   ├─ Update payout status
   └─ Notify miner (Telegram)

6. ARCHIE AI MONITORING
   Continuous (every 60s)
   ├─ Monitor pool hashrate
   ├─ Check worker health
   ├─ Optimize difficulty
   ├─ Detect anomalies
   ├─ Predict profitability
   └─ Provide Telegram support
```

---

## Database Schema

### Core Pool Tables

```sql
-- Workers (Miners)
CREATE TABLE workers (
    id SERIAL PRIMARY KEY,
    wallet VARCHAR(200) NOT NULL,
    worker_name VARCHAR(100) DEFAULT 'default',
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    last_share TIMESTAMP,
    total_shares BIGINT DEFAULT 0,
    total_invalid_shares BIGINT DEFAULT 0,
    total_blocks_found INTEGER DEFAULT 0,
    current_hashrate DECIMAL(20, 2) DEFAULT 0,
    average_hashrate DECIMAL(20, 2) DEFAULT 0,
    difficulty DECIMAL(10, 2) DEFAULT 1.0,
    status VARCHAR(20) DEFAULT 'active',
    ip_address INET,
    user_agent VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(wallet, worker_name)
);

-- Shares (Partitioned by month for performance)
CREATE TABLE shares (
    id BIGSERIAL PRIMARY KEY,
    wallet VARCHAR(200) NOT NULL,
    worker VARCHAR(100) NOT NULL,
    difficulty DECIMAL(10, 2) NOT NULL,
    blockchain VARCHAR(50) NOT NULL,
    is_block BOOLEAN DEFAULT FALSE,
    block_height BIGINT,
    block_hash VARCHAR(128),
    submitted_at TIMESTAMP NOT NULL,
    valid BOOLEAN DEFAULT TRUE,
    response_time_ms INTEGER,
    ip_address INET
) PARTITION BY RANGE (submitted_at);

-- Blocks Found
CREATE TABLE blocks (
    id SERIAL PRIMARY KEY,
    blockchain VARCHAR(50) NOT NULL,
    height BIGINT NOT NULL,
    hash VARCHAR(128),
    difficulty DECIMAL(30, 2),
    finder_wallet VARCHAR(200) NOT NULL,
    finder_worker VARCHAR(100) NOT NULL,
    reward DECIMAL(20, 8),
    found_at TIMESTAMP NOT NULL,
    confirmed_at TIMESTAMP,
    orphaned_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',
    confirmations INTEGER DEFAULT 0,
    payout_processed BOOLEAN DEFAULT FALSE,
    payout_amount DECIMAL(20, 8),
    pool_fee DECIMAL(20, 8),
    game_allocated BOOLEAN DEFAULT FALSE,
    notes TEXT,
    UNIQUE(blockchain, height)
);

-- Payouts
CREATE TABLE payouts (
    id SERIAL PRIMARY KEY,
    wallet VARCHAR(200) NOT NULL,
    worker VARCHAR(100),
    amount DECIMAL(20, 8) NOT NULL,
    blockchain VARCHAR(50) NOT NULL,
    block_height BIGINT,
    txid VARCHAR(128),
    created_at TIMESTAMP DEFAULT NOW(),
    queued_at TIMESTAMP,
    sent_at TIMESTAMP,
    confirmed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    notes TEXT
);
```

### Flexible Payout System

```sql
-- Miner Preferences
CREATE TABLE miner_preferences (
    wallet VARCHAR(200) PRIMARY KEY,
    payout_coin VARCHAR(10) DEFAULT 'RVN',
    payout_address VARCHAR(200),
    minimum_payout DECIMAL(20, 8) DEFAULT 1.0,
    auto_convert BOOLEAN DEFAULT TRUE,
    email VARCHAR(255),
    telegram_id VARCHAR(50),
    notification_preferences JSONB DEFAULT '{"blocks": true, "payouts": true, "issues": true}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Conversion Queue
CREATE TABLE conversion_queue (
    id SERIAL PRIMARY KEY,
    miner_wallet VARCHAR(200) NOT NULL,
    from_coin VARCHAR(10) NOT NULL,
    from_amount DECIMAL(20, 8) NOT NULL,
    to_coin VARCHAR(10) NOT NULL,
    estimated_amount DECIMAL(20, 8),
    actual_amount DECIMAL(20, 8),
    exchange_rate DECIMAL(20, 8),
    exchange_provider VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    completed_at TIMESTAMP,
    txid VARCHAR(128),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Conversion History
CREATE TABLE conversion_history (
    id BIGSERIAL PRIMARY KEY,
    miner_wallet VARCHAR(200) NOT NULL,
    from_coin VARCHAR(10) NOT NULL,
    from_amount DECIMAL(20, 8) NOT NULL,
    to_coin VARCHAR(10) NOT NULL,
    to_amount DECIMAL(20, 8) NOT NULL,
    exchange_rate DECIMAL(20, 8) NOT NULL,
    fees_paid DECIMAL(20, 8),
    provider VARCHAR(50),
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Exchange Rates Cache
CREATE TABLE exchange_rates_cache (
    id SERIAL PRIMARY KEY,
    from_coin VARCHAR(10) NOT NULL,
    to_coin VARCHAR(10) NOT NULL,
    rate DECIMAL(20, 8) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_coin, to_coin, provider, timestamp)
);
```

### Game Economy Integration

```sql
-- Game Accounts
CREATE TABLE game_accounts (
    player_id VARCHAR(100) PRIMARY KEY,
    player_name VARCHAR(100),
    balance DECIMAL(20, 2) DEFAULT 0,
    total_earned DECIMAL(20, 2) DEFAULT 0,
    total_withdrawn DECIMAL(20, 2) DEFAULT 0,
    mining_wallet VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_played TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active'
);

-- Game Transactions
CREATE TABLE game_transactions (
    id BIGSERIAL PRIMARY KEY,
    player_id VARCHAR(100) NOT NULL,
    amount DECIMAL(20, 2) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Reward Events
CREATE TABLE reward_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL UNIQUE,
    credits_awarded DECIMAL(10, 2) NOT NULL,
    description TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO reward_events (event_type, credits_awarded, description) VALUES
    ('match_win', 50, 'Win a match'),
    ('match_top3', 25, 'Finish in top 3'),
    ('daily_login', 10, 'Daily login bonus'),
    ('ad_watched', 5, 'Watch a video ad'),
    ('mining_bonus', 10, 'Mining while playing bonus'),
    ('achievement_first_kill', 100, 'Get your first kill'),
    ('achievement_10_wins', 500, 'Win 10 matches'),
    ('referral', 1000, 'Refer a friend who plays 5 matches');

-- Game Funding (Pool allocation + Ad revenue)
CREATE TABLE game_funding (
    id SERIAL PRIMARY KEY,
    amount DECIMAL(20, 8) NOT NULL,
    source VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Service Components

### 1. NOMP Stratum Server

The pool uses NOMP (Node Open Mining Portal) for stratum mining connections.

**Configuration:** `config/pool_configs/ravencoin.json`

```json
{
    "enabled": true,
    "coin": "ravencoin.json",
    "address": "${RVN_POOL_ADDRESS}",
    "rewardRecipients": {
        "${RVN_POOL_ADDRESS}": 0.5
    },
    "paymentProcessing": {
        "enabled": true,
        "paymentInterval": 600,
        "minimumPayment": 1.0,
        "maxBlocksPerPayment": 10
    },
    "ports": {
        "3333": {
            "diff": 0.05,
            "varDiff": {
                "minDiff": 0.01,
                "maxDiff": 100,
                "targetTime": 10,
                "retargetTime": 60,
                "variancePercent": 30
            }
        },
        "3334": {
            "diff": 1,
            "varDiff": {
                "minDiff": 0.5,
                "maxDiff": 1000,
                "targetTime": 10,
                "retargetTime": 60,
                "variancePercent": 30
            }
        }
    }
}
```

### 2. Share Validator Service

Processes shares from Redis queue and validates them.

**Key Features:**
- Batch processing for performance
- Async validation
- Block found notifications
- Worker stats updates

### 3. Payout Manager Service

Calculates and processes payouts using PPLNS algorithm.

**Key Features:**
- PPLNS (Pay Per Last N Shares) calculation
- Miner preference checking
- Conversion queue integration
- Game economy allocation (20% of pool fees)

### 4. Conversion Engine Service

Handles cryptocurrency conversions via exchange APIs.

**Key Features:**
- Exchange rate caching
- Changelly API integration
- Game credits conversion
- Rate limiting

---

## Management Interface

### Dashboard Pages

#### 1. Main Dashboard (`/`)
- Pool hashrate (real-time)
- Active miners count
- Blocks found (24h)
- Pool luck percentage
- Hashrate chart
- Active miners table
- Recent blocks table

#### 2. Miners Management (`/miners`)
- Real-time miner list with search/filter
- Individual miner details
- Hashrate charts per miner
- Payout preferences editor
- Worker management
- Ban/unban functionality

#### 3. Blocks Explorer (`/blocks`)
- Block history with status filters
- Block details view
- Finder information
- Payout breakdown per block

#### 4. Payouts Management (`/payouts`)
- Payout history
- Pending payouts queue
- Manual payout trigger
- Payout statistics

#### 5. Conversions Dashboard (`/conversions`)
- Conversion queue status
- Exchange rates display
- Conversion history
- Manual conversion trigger

#### 6. Analytics (`/analytics`)
- Pool hashrate over time
- Revenue breakdown
- Miner growth charts
- AI predictions

#### 7. Settings Panel (`/settings`)
- Pool fee configuration
- PPLNS window settings
- Notification settings
- Exchange integration

---

## API Documentation

### Authentication

All API endpoints use JWT authentication for administrative functions.

```javascript
// Get auth token
POST /api/v1/auth/login
Request: {
  "username": "admin",
  "password": "your_password"
}
Response: {
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires": "2026-01-16T10:00:00Z"
}

// Use token in subsequent requests
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Pool Endpoints

```javascript
// Get pool statistics
GET /api/v1/stats
Response: {
  "pool": {
    "hashrate": 1234567890,
    "active_workers": 150,
    "total_shares_24h": 1000000,
    "blocks_found_24h": 5,
    "blocks_pending": 2,
    "pool_luck": 102.5,
    "fee": 0.5
  },
  "network": {
    "difficulty": 123456789,
    "hashrate": 10000000000,
    "height": 5000000,
    "pool_percentage": 12.35
  }
}

// Get pool history
GET /api/v1/stats/history?period=24h
```

### Miner Endpoints

```javascript
// List miners
GET /api/v1/miners?limit=50&offset=0&status=active

// Get miner details
GET /api/v1/miners/{wallet}

// Update miner preferences
PUT /api/v1/miners/{wallet}/preferences
Request: {
  "payout_coin": "BTC",
  "payout_address": "bc1...",
  "minimum_payout": 0.001,
  "auto_convert": true
}

// Ban/unban miner
POST /api/v1/miners/{wallet}/ban
```

### Block Endpoints

```javascript
// Get blocks
GET /api/v1/blocks?limit=20&status=confirmed

// Get block details
GET /api/v1/blocks/{height}
```

### Payout Endpoints

```javascript
// Get payouts
GET /api/v1/payouts?wallet=R...&limit=20

// Get pending payouts
GET /api/v1/payouts/pending

// Manually trigger payout (admin only)
POST /api/v1/payouts/process

// Get payout statistics
GET /api/v1/payouts/stats
```

### Conversion Endpoints

```javascript
// Get conversion queue
GET /api/v1/conversions/queue

// Get conversion history
GET /api/v1/conversions/history?limit=50

// Get exchange rates
GET /api/v1/rates?from=RVN&to=BTC,ETH,LTC

// Manually trigger conversion (admin only)
POST /api/v1/conversions/process/{id}
```

---

## Deployment Instructions

### Prerequisites

- Docker & Docker Compose installed
- Ubuntu 24.04 LTS
- 500GB+ disk space
- 16GB+ RAM recommended

### Directory Structure

```
/mnt/HomeLab/archie-pool/
├── docker-compose.yml
├── .env
├── config/
│   ├── ravencoin.conf
│   ├── nomp-config.json
│   └── pool_configs/
├── sql/
│   ├── init.sql
│   └── migrations/
├── services/
│   ├── nomp/
│   ├── share-validator/
│   ├── payout-manager/
│   ├── conversion-engine/
│   └── pool-api/
├── dashboard/
├── data/
├── logs/
└── backups/
```

### Environment Variables

```bash
# Pool Information
POOL_NAME="Archie Pool"
POOL_DOMAIN=pool.kytranempowerment.com
POOL_IP=192.168.1.250

# Wallet Addresses (From Zelcore)
RVN_POOL_ADDRESS=YOUR_RVN_ADDRESS
BEAM_POOL_ADDRESS=YOUR_BEAM_ADDRESS
XMR_POOL_ADDRESS=YOUR_XMR_ADDRESS

# Database Configuration
DB_PASSWORD=STRONG_PASSWORD
POSTGRES_DB=archie_pool
POSTGRES_USER=pooluser

# Ravencoin Node
RVN_RPC_USER=poolrpc
RVN_RPC_PASSWORD=STRONG_PASSWORD
RVN_RPC_PORT=8766

# Redis
REDIS_PASSWORD=STRONG_PASSWORD

# Pool Fees
POOL_FEE=0.005
CONVERSION_FEE=0.01

# Payouts
MIN_PAYOUT_RVN=1.0
PAYOUT_INTERVAL=3600
PPLNS_WINDOW=10000

# Exchange API
CHANGELLY_API_KEY=YOUR_KEY
CHANGELLY_API_SECRET=YOUR_SECRET
```

### Deployment Script

```bash
#!/bin/bash
# File: scripts/deploy.sh

set -e

POOL_DIR="/mnt/HomeLab/archie-pool"

echo "Starting Archie Pool deployment..."

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed"
    exit 1
fi

# Check environment file
if [ ! -f "$POOL_DIR/.env" ]; then
    echo ".env file not found"
    exit 1
fi

# Stop existing containers
cd $POOL_DIR
docker-compose down

# Pull latest images
docker-compose pull

# Build custom images
docker-compose build

# Start services
docker-compose up -d

# Wait for services
sleep 10

# Run database migrations
docker exec archie_pool_postgres psql -U pooluser -d archie_pool -f /migrations/init.sql

# Check health
docker-compose ps

echo "Deployment complete!"
echo "Dashboard: http://192.168.1.250:8084"
echo "Stratum: stratum+tcp://192.168.1.250:3333"
```

### Port Allocation

```
3333: Stratum (low difficulty)
3334: Stratum (high difficulty)
8084: Pool web dashboard
8766: Ravencoin RPC (internal)
8767: Ravencoin P2P
5433: PostgreSQL (internal)
6380: Redis (internal)
5000: Pool API (internal)
```

---

## Game Integration

### Game Credits System

**Conversion Rate:** 1000 credits = $1 USD

**Earning Methods:**
- Mining payouts converted to credits
- Match wins (50 credits)
- Top 3 finishes (25 credits)
- Daily login bonus (10 credits)
- Watching ads (5 credits)
- Mining while playing bonus (10 credits)
- Referrals (1000 credits)

### Account Linking

```python
@app.route('/api/link-accounts', methods=['POST'])
def link_accounts():
    """Link mining wallet to game account"""
    data = request.json
    mining_wallet = data.get('mining_wallet')
    player_id = data.get('player_id')

    # Link accounts in database
    # Transfer pending mining earnings to game balance
    # Convert to game credits
```

---

## Revenue Model

### Income Sources

1. **Pool Fees (0.5%)**
   - 100 miners @ 100 MH/s = ~$0.75/month
   - 1000 miners = ~$7.50/month

2. **Conversion Fees (1%)**
   - 50% of miners convert = better margins
   - Average $37.50/month at scale

3. **Game Revenue**
   - Ad revenue: $200-500/month
   - Premium features: $100-300/month

### Cost Structure

**Fixed Monthly:**
- Server hosting: $0 (owned hardware)
- Domain: $1
- SSL: Free (Let's Encrypt)

**Variable:**
- Exchange fees: ~0.1% of conversions
- Electricity: ~$20-30/month
- Marketing: $100-500/month (optional)

**Profit Margins: 70-90%**

---

## Troubleshooting

### Common Issues

**Miners can't connect:**
```bash
# Check stratum server
docker logs pool_nomp

# Check port accessibility
netstat -tlnp | grep 3333

# Check firewall
sudo ufw status
```

**Blockchain not syncing:**
```bash
# Check sync status
docker exec ravencoin_node raven-cli getblockchaininfo

# Check peers
docker exec ravencoin_node raven-cli getpeerinfo
```

**Database issues:**
```bash
# Check connections
docker exec pool_postgres psql -U pooluser -d archie_pool -c "SELECT count(*) FROM pg_stat_activity;"

# Backup database
docker exec pool_postgres pg_dump -U pooluser archie_pool > backup.sql
```

---

## Integration with A.R.C.H.I.E. Bridge

The Archie Pool will integrate with the A.R.C.H.I.E. Bridge module:

- **BRIDGE Station**: Pool monitoring station
- **AI Optimization**: Difficulty adjustment, profitability predictions
- **Telegram Bot**: 24/7 miner support via A.R.C.H.I.E.
- **Remote Nodes**: VPN contributors can provide LLM power when not mining

---

*Document Version: 1.0*
*Last Updated: 2026-01-16*
*For: Kytran Empowerment Inc. / Archie Pool Project*
