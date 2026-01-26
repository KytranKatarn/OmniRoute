# Mining Integration with A.R.C.H.I.E. Nodes

## Evaluation and Implementation Plan

**Version**: 1.0.0
**Last Updated**: 2026-01-22
**Status**: Approved for Implementation

---

## 1. Executive Summary

### Recommendation: **INTEGRATE (Optional Feature)**

Mining should be integrated with the node system as an **optional feature** that:
- Utilizes idle GPU time for passive income
- Automatically pauses for AI workloads (AI always takes priority)
- Reports to the central Archie Pool dashboard
- Is disabled by default, opt-in per node

### Rationale

| Factor | Analysis |
|--------|----------|
| **GPU Utilization** | Nodes often idle 80%+ of the time waiting for AI requests |
| **Revenue** | Even modest mining covers electricity costs |
| **Complexity** | Low - mining software is mature and stable |
| **Conflict** | Minimal - scheduler preempts mining for AI |
| **User Value** | High - passive income from existing hardware |

---

## 2. Integration Architecture

### 2.1 GPU Scheduler Design

```
┌────────────────────────────────────────────────────────────┐
│                    Node GPU Scheduler                       │
├────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐ │
│   │  AI Queue   │ >>> │  Scheduler  │ <<< │ Mine Queue  │ │
│   │  (Priority) │     │             │     │  (Idle)     │ │
│   └─────────────┘     └──────┬──────┘     └─────────────┘ │
│                              │                             │
│                              ▼                             │
│                    ┌─────────────────┐                     │
│                    │      GPU        │                     │
│                    │   (Exclusive)   │                     │
│                    └─────────────────┘                     │
│                                                             │
│   States:                                                  │
│   - AI_ACTIVE: Mining suspended, AI processing            │
│   - MINING: No AI requests, mining active                 │
│   - IDLE: Neither (GPU temp cooldown, etc.)               │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Priority Rules

```python
PRIORITY_RULES = {
    1: 'ai_inference',    # Immediate, preempts mining
    2: 'ai_training',     # Scheduled, preempts mining
    3: 'video_generation', # Long-running, preempts mining
    4: 'image_generation', # Medium, preempts mining
    5: 'mining',          # Background, yields to all above
}

# Mining resumes after:
# - AI task completes
# - GPU temp drops below threshold
# - Minimum idle time passes (30s default)
```

### 2.3 Component Interaction

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ Node Client  │      │    Bridge    │      │ Archie Pool  │
│              │      │              │      │              │
│ ┌──────────┐ │      │ ┌──────────┐ │      │ ┌──────────┐ │
│ │GPU Sched │◄├──────┤►│AI Router │ │      │ │  Stratum │ │
│ └────┬─────┘ │      │ └──────────┘ │      │ └────▲─────┘ │
│      │       │      │              │      │      │       │
│ ┌────▼─────┐ │      │ ┌──────────┐ │      │ ┌────┴─────┐ │
│ │  Miner   │◄├──────┼─┤Mining Tab│◄├──────┼─┤ Pool API │ │
│ │(kawpowm) │ │      │ └──────────┘ │      │ └──────────┘ │
│ └──────────┘ │      │              │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
      │                                            ▲
      └────────────────────────────────────────────┘
               Stratum Connection (3333)
```

---

## 3. Implementation Details

### 3.1 New Files

```
/mnt/archie_brain/node_client/
├── gpu_scheduler.py     # GPU task scheduling
├── miner_manager.py     # Mining process control
└── mining_config.py     # Mining configuration
```

### 3.2 GPU Scheduler

```python
# /mnt/archie_brain/node_client/gpu_scheduler.py
"""
GPU Scheduler - Manages GPU access between AI and Mining
"""
import threading
import time
from enum import Enum
from typing import Callable, Optional

class GPUState(Enum):
    IDLE = "idle"
    AI_ACTIVE = "ai_active"
    MINING = "mining"
    COOLDOWN = "cooldown"

class GPUScheduler:
    def __init__(self, config):
        self.config = config
        self.state = GPUState.IDLE
        self.lock = threading.Lock()
        self.ai_callback: Optional[Callable] = None
        self.mining_callback: Optional[Callable] = None
        self.last_ai_task = 0
        self.gpu_temp = 0

    def request_gpu(self, task_type: str, priority: int = 5) -> bool:
        """
        Request GPU access for a task.
        Returns True if granted, False if must wait.
        """
        with self.lock:
            # AI always gets GPU
            if priority < 5:  # AI task
                if self.state == GPUState.MINING:
                    self._pause_mining()
                self.state = GPUState.AI_ACTIVE
                self.last_ai_task = time.time()
                return True

            # Mining only when idle
            if priority == 5:  # Mining
                if self.state == GPUState.IDLE:
                    if self._can_mine():
                        self.state = GPUState.MINING
                        return True
                return False

    def release_gpu(self, task_type: str):
        """Release GPU after task completion"""
        with self.lock:
            if task_type != 'mining':
                self.last_ai_task = time.time()
                self.state = GPUState.COOLDOWN
                # Schedule mining resume after cooldown
                threading.Timer(
                    self.config.mining_idle_delay,
                    self._try_resume_mining
                ).start()
            else:
                self.state = GPUState.IDLE

    def _can_mine(self) -> bool:
        """Check if mining is allowed"""
        if not self.config.mining_enabled:
            return False
        if self.gpu_temp > self.config.mining_temp_limit:
            return False
        if time.time() - self.last_ai_task < self.config.mining_idle_delay:
            return False
        return True

    def _pause_mining(self):
        """Pause mining for AI task"""
        if self.mining_callback:
            self.mining_callback('pause')

    def _try_resume_mining(self):
        """Try to resume mining after cooldown"""
        with self.lock:
            if self.state == GPUState.COOLDOWN and self._can_mine():
                self.state = GPUState.MINING
                if self.mining_callback:
                    self.mining_callback('resume')
```

### 3.3 Miner Manager

```python
# /mnt/archie_brain/node_client/miner_manager.py
"""
Miner Manager - Controls mining process
"""
import subprocess
import threading
import logging
from typing import Dict, Any

logger = logging.getLogger('archie.miner')

class MinerManager:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.stats = {
            'hashrate': 0,
            'shares_accepted': 0,
            'shares_rejected': 0,
            'uptime': 0
        }
        self._monitor_thread = None

    def start(self) -> bool:
        """Start mining process"""
        if self.process and self.process.poll() is None:
            return True  # Already running

        cmd = self._build_command()
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True
            )
            self._start_monitor()
            logger.info("Mining started")
            return True
        except Exception as e:
            logger.error(f"Failed to start mining: {e}")
            return False

    def stop(self) -> bool:
        """Stop mining process"""
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None
            logger.info("Mining stopped")
        return True

    def pause(self):
        """Pause mining (SIGSTOP on Linux)"""
        if self.process:
            self.process.send_signal(19)  # SIGSTOP
            logger.info("Mining paused for AI task")

    def resume(self):
        """Resume mining (SIGCONT on Linux)"""
        if self.process:
            self.process.send_signal(18)  # SIGCONT
            logger.info("Mining resumed")

    def _build_command(self) -> str:
        """Build miner command based on config"""
        # Using kawpowminer for RVN (Archie Pool)
        return (
            f"kawpowminer "
            f"-P stratum+tcp://{self.config.mining_wallet}."
            f"{self.config.mining_worker}@{self.config.mining_pool} "
            f"--HWMON 1 "
            f"--dag-load-mode sequential "
            f"--nocolor"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get current mining statistics"""
        return self.stats.copy()

    def _start_monitor(self):
        """Start monitoring thread for miner output"""
        def monitor():
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if line:
                    self._parse_output(line.decode().strip())
        self._monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._monitor_thread.start()

    def _parse_output(self, line: str):
        """Parse miner output for stats"""
        # Parse hashrate, shares, etc. from miner output
        if 'Speed' in line:
            # Extract hashrate
            pass
        elif 'Accepted' in line:
            self.stats['shares_accepted'] += 1
```

### 3.4 Configuration

```python
# /mnt/archie_brain/node_client/mining_config.py
"""
Mining Configuration
"""
from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class MiningConfig:
    # Enable/Disable
    enabled: bool = False

    # Pool Configuration
    pool: str = "stratum+tcp://pool.kytranempowerment.com:3333"
    wallet: str = ""
    worker: str = "{hostname}"

    # Scheduling
    only_when_idle: bool = True
    idle_delay_seconds: int = 30
    resume_delay_seconds: int = 5

    # Limits
    gpu_power_limit_percent: int = 80
    temp_limit_celsius: int = 75
    max_fan_speed_percent: int = 80

    # Reporting
    report_to_central: bool = True
    report_interval_seconds: int = 60

    @classmethod
    def from_env(cls) -> 'MiningConfig':
        return cls(
            enabled=os.getenv('ARCHIE_MINING_ENABLED', 'false').lower() == 'true',
            pool=os.getenv('ARCHIE_MINING_POOL', cls.pool),
            wallet=os.getenv('ARCHIE_MINING_WALLET', ''),
            worker=os.getenv('ARCHIE_MINING_WORKER', '{hostname}'),
            temp_limit_celsius=int(os.getenv('ARCHIE_MINING_TEMP_LIMIT', '75')),
        )
```

---

## 4. Heartbeat Integration

### 4.1 Extended Heartbeat Payload

```python
# Add to health_monitor.py get_heartbeat_payload()
def get_mining_stats(self) -> Dict[str, Any]:
    """Get mining statistics for heartbeat"""
    if not self.mining_manager:
        return {'mining_enabled': False}

    stats = self.mining_manager.get_stats()
    return {
        'mining_enabled': True,
        'mining_active': self.gpu_scheduler.state == GPUState.MINING,
        'hashrate_mh': stats.get('hashrate', 0),
        'shares_accepted': stats.get('shares_accepted', 0),
        'shares_rejected': stats.get('shares_rejected', 0),
        'mining_uptime_seconds': stats.get('uptime', 0),
        'estimated_daily_rvn': self._estimate_earnings(stats.get('hashrate', 0)),
    }
```

### 4.2 Database Schema

```sql
-- Add to remote_nodes table
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS mining_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS mining_wallet VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS current_hashrate DECIMAL(10,2) DEFAULT 0;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS total_shares_accepted INTEGER DEFAULT 0;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS mining_uptime_seconds INTEGER DEFAULT 0;

-- Mining statistics history
CREATE TABLE IF NOT EXISTS node_mining_stats (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) REFERENCES remote_nodes(node_id),
    hashrate_mh DECIMAL(10,2),
    shares_accepted INTEGER,
    shares_rejected INTEGER,
    gpu_temp INTEGER,
    gpu_power INTEGER,
    recorded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_mining_stats_node ON node_mining_stats(node_id);
CREATE INDEX idx_mining_stats_time ON node_mining_stats(recorded_at);

-- Aggregate view for Pool dashboard
CREATE OR REPLACE VIEW v_network_mining_stats AS
SELECT
    COUNT(DISTINCT node_id) FILTER (WHERE mining_enabled AND current_hashrate > 0) as active_miners,
    SUM(current_hashrate) as total_hashrate_mh,
    SUM(total_shares_accepted) as total_shares,
    AVG(current_hashrate) FILTER (WHERE current_hashrate > 0) as avg_hashrate_mh
FROM remote_nodes
WHERE is_active = true;
```

---

## 5. Bridge UI Integration

### 5.1 Mining Tab in Bridge

Add to `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`:

```html
<!-- Mining Tab -->
<div id="mining-tab" class="tab-content" style="display: none;">
    <div class="section-header">
        <h3>Network Mining</h3>
        <div class="mining-controls">
            <button onclick="refreshMiningStats()" class="btn btn-secondary">
                <i data-lucide="refresh-cw"></i> Refresh
            </button>
        </div>
    </div>

    <!-- Network Stats -->
    <div class="mining-network-stats">
        <div class="stat-card">
            <div class="stat-value" id="total-hashrate">0 MH/s</div>
            <div class="stat-label">Network Hashrate</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="active-miners">0</div>
            <div class="stat-label">Active Miners</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="total-shares">0</div>
            <div class="stat-label">Shares (24h)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="estimated-daily">0 RVN</div>
            <div class="stat-label">Est. Daily Earnings</div>
        </div>
    </div>

    <!-- Per-Node Mining Status -->
    <div class="mining-nodes-grid" id="mining-nodes-container">
        <!-- Populated by JavaScript -->
    </div>
</div>
```

### 5.2 API Endpoint

```python
@bridge_bp.route('/api/mining/stats', methods=['GET'])
def get_mining_stats():
    """Get network mining statistics"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Network totals
    cur.execute("SELECT * FROM v_network_mining_stats")
    network = cur.fetchone()

    # Per-node stats
    cur.execute("""
        SELECT node_id, node_name, vpn_ip, current_hashrate,
               total_shares_accepted, mining_enabled, gpu_model
        FROM remote_nodes
        WHERE is_active = true AND mining_enabled = true
        ORDER BY current_hashrate DESC
    """)
    nodes = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'network': dict(network) if network else {},
        'nodes': [dict(n) for n in nodes]
    })
```

---

## 6. Integration with Archie Pool

### 6.1 Unified Dashboard

The Pool Management module (`/tools/pool-management`) will show:
- Combined hashrate from all nodes
- Per-node contribution breakdown
- Worker auto-naming: `{node_name}_{node_id}`

### 6.2 Worker Identification

```python
# Worker name format for pool
def get_worker_name(node_name: str, node_id: str) -> str:
    """Generate unique worker name for pool identification"""
    short_id = node_id.split('_')[1][:8]
    return f"{node_name}_{short_id}"

# Example: KYTRAN_3d435e82
```

### 6.3 Payout Integration

Nodes can optionally contribute to a shared pool wallet:
- Individual wallets (default)
- Shared organization wallet (opt-in)

---

## 7. Installation & Configuration

### 7.1 Enable Mining on Node

```bash
# Edit node config
nano /etc/archie-node/config.py

# Add:
MINING_ENABLED = True
MINING_WALLET = "your-rvn-wallet-address"
MINING_POOL = "stratum+tcp://pool.kytranempowerment.com:3333"
MINING_TEMP_LIMIT = 75

# Restart node
sudo systemctl restart archie-node
```

### 7.2 Via Interactive Installer

```
=====================================
       Mining Configuration
=====================================

Enable mining when GPU is idle? (y/n): y

Enter RVN wallet address: RVNxxxxxxxxxxxxxxxxxxx

Mining pool:
  [1] Archie Pool (pool.kytranempowerment.com) - Recommended
  [2] Custom pool
  Select: 1

GPU temperature limit (Celsius): 75
GPU power limit (%): 80

Configuration saved!
```

---

## 8. Safety & Limits

### 8.1 Automatic Safeguards

```python
SAFETY_LIMITS = {
    # Temperature
    'gpu_temp_warning': 70,      # Reduce power at 70°C
    'gpu_temp_critical': 80,     # Stop mining at 80°C
    'gpu_temp_emergency': 90,    # Emergency shutdown

    # Power
    'max_power_percent': 80,     # Never exceed 80% TDP
    'idle_power_percent': 50,    # Reduce when nearly idle

    # Scheduling
    'ai_preempt_timeout': 5,     # Seconds to pause mining
    'cooldown_after_ai': 30,     # Seconds before resuming
}
```

### 8.2 Health Monitoring

```python
def check_mining_health(self) -> Dict[str, Any]:
    """Check if mining is healthy"""
    issues = []

    if self.gpu_temp > SAFETY_LIMITS['gpu_temp_warning']:
        issues.append(f"GPU temp high: {self.gpu_temp}°C")

    if self.shares_rejected / max(self.shares_accepted, 1) > 0.05:
        issues.append(f"High reject rate: {self.reject_rate:.1%}")

    if self.hashrate < self.expected_hashrate * 0.8:
        issues.append(f"Low hashrate: {self.hashrate} MH/s")

    return {
        'healthy': len(issues) == 0,
        'issues': issues
    }
```

---

## 9. Implementation Phases

### Phase 1: Core Infrastructure
- [ ] gpu_scheduler.py
- [ ] miner_manager.py
- [ ] mining_config.py

### Phase 2: Node Integration
- [ ] Heartbeat mining stats
- [ ] Database schema updates
- [ ] Health monitor integration

### Phase 3: Bridge Integration
- [ ] Mining tab in Bridge UI
- [ ] API endpoints
- [ ] Per-node controls

### Phase 4: Pool Integration
- [ ] Link to Archie Pool dashboard
- [ ] Worker auto-registration
- [ ] Unified statistics

---

## 10. Summary

**Mining integration is recommended** because:

1. **Non-intrusive**: AI always takes priority
2. **Revenue generating**: Covers electricity, provides income
3. **Well-architected**: Clean separation of concerns
4. **Optional**: Disabled by default, user choice
5. **Monitored**: Full visibility in Bridge dashboard
6. **Safe**: Temperature limits, power limits, auto-pause

This transforms idle GPUs into revenue-generating assets while maintaining A.R.C.H.I.E.'s primary mission of AI processing.
