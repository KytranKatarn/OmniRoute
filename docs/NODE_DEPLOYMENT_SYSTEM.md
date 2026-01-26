# A.R.C.H.I.E. Node Deployment System

## Complete Guide to Deploying AI Nodes

**Version**: 2.0.0
**Last Updated**: 2026-01-22
**Status**: Implementation Ready

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Hardware Requirements](#3-hardware-requirements)
4. [AI Services Catalog](#4-ai-services-catalog)
5. [Installation Guide](#5-installation-guide)
6. [VPN Configuration](#6-vpn-configuration)
7. [Mining Integration](#7-mining-integration)
8. [Node Management](#8-node-management)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

The A.R.C.H.I.E. Node Deployment System enables distributed AI processing across multiple machines. Nodes can be:

- **Local Network Nodes**: Machines on the same LAN as A.R.C.H.I.E.
- **VPN Nodes**: Remote machines connected via VPN
- **Hybrid Nodes**: Running both AI services and mining operations

### Key Features

- **Automatic Hardware Detection**: Analyzes CPU, GPU, RAM, storage
- **Smart Service Recommendations**: Suggests services based on capabilities
- **Cross-Platform Support**: Windows and Linux installers
- **VPN Auto-Connect**: Seamless connection for remote nodes
- **Dynamic Load Balancing**: Bridge routes to optimal node
- **GPU Scheduling**: Balances AI inference and optional mining

---

## 2. Architecture

```
                     ┌─────────────────────────────────────┐
                     │     vpn.kytranempowerment.com       │
                     │         (WireGuard VPN)             │
                     └──────────────┬──────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌───────────────┐
│  Local Node   │         │  A.R.C.H.I.E.   │         │  Remote Node  │
│  192.168.1.x  │◄───────►│   (Central)     │◄───────►│  10.0.0.x     │
│               │   LAN   │  192.168.1.200  │   VPN   │  (via VPN)    │
└───────────────┘         └────────┬────────┘         └───────────────┘
                                   │
                          ┌────────┴────────┐
                          │                 │
                    ┌─────▼─────┐     ┌─────▼─────┐
                    │  Bridge   │     │   Pool    │
                    │  Router   │     │  Manager  │
                    └───────────┘     └───────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **Node Client** | Runs on each node, sends heartbeats |
| **Bridge Router** | Routes AI requests to best node |
| **VPN Server** | Connects remote nodes securely |
| **Pool Manager** | Coordinates mining (optional) |

---

## 3. Hardware Requirements

### Minimum Requirements

| Tier | CPU | RAM | GPU | Use Cases |
|------|-----|-----|-----|-----------|
| **Basic** | 4 cores | 8GB | None | LLM (CPU), lightweight tasks |
| **Standard** | 8 cores | 16GB | 6GB VRAM | LLM + Image generation |
| **Advanced** | 12 cores | 32GB | 12GB VRAM | LLM + Image + Video |
| **Professional** | 16+ cores | 64GB | 24GB+ VRAM | Everything + Mining |

### GPU Compatibility

| Vendor | Minimum | Recommended | Notes |
|--------|---------|-------------|-------|
| **NVIDIA** | GTX 1060 6GB | RTX 3080+ | Best support, CUDA |
| **AMD** | RX 580 8GB | RX 6800+ | ROCm required (Linux) |
| **Intel** | Arc A750 | Arc A770 | Limited support |

### Recommended Configurations

**Budget Node ($300-500)**
```
- Used Dell Optiplex / HP ProDesk
- i5/i7 6th-10th gen
- 16GB RAM
- GTX 1070/1080 (used)
- 256GB SSD
→ Good for: Ollama, Foocus, basic inference
```

**Mid-Range Node ($800-1200)**
```
- AMD Ryzen 5600/5700X or Intel i5-12400
- 32GB RAM
- RTX 3070/3080
- 1TB NVMe SSD
→ Good for: All image generation, video generation
```

**Professional Node ($2000+)**
```
- AMD Ryzen 9 / Intel i9
- 64GB RAM
- RTX 4090 / RTX A5000
- 2TB NVMe SSD
→ Good for: Everything including HunyuanVideo, mining
```

---

## 4. AI Services Catalog

### 4.1 LLM Runners (Text Generation)

| Service | Platform | Difficulty | Best For |
|---------|----------|------------|----------|
| **Ollama** | Win/Linux/Mac | Easy | General use, development |
| **llama.cpp** | Win/Linux/Mac | Medium | Edge devices, max performance |
| **vLLM** | Linux only | Advanced | Production, high throughput |
| **LocalAI** | Win/Linux | Medium | OpenAI API compatibility |

**Default Models to Install:**
```yaml
essential:
  - llama3.2:3b        # 2GB, fast general purpose
  - mistral:7b         # 4GB, balanced

coding:
  - deepseek-coder-v2:16b  # 9GB, excellent for code
  - qwen2.5-coder:7b       # 4GB, fast coding

specialized:
  - phi3:mini          # 2GB, efficient reasoning
  - gemma2:9b          # 5GB, Google's model
```

### 4.2 Text-to-Image Generators

| Service | VRAM | Style | Ease |
|---------|------|-------|------|
| **Foocus** | 4GB+ | SDXL, beginner-friendly | Easy |
| **ComfyUI** | 4GB+ | Node-based, most flexible | Advanced |
| **Automatic1111** | 4GB+ | Extension ecosystem | Medium |
| **InvokeAI** | 4GB+ | Professional UI | Medium |

**Supported Models:**
- Stable Diffusion 1.5, 2.1, XL, 3.5
- FLUX.1 (Dev/Schnell) - New standard
- Playground V2.5
- Juggernaut XL, RealVisXL, etc.

### 4.3 Text-to-Video Generators

| Service | VRAM | Quality | Speed |
|---------|------|---------|-------|
| **CogVideoX** | 6GB+ | Good | Fast |
| **Open-Sora 2.0** | 8GB+ | Very Good | Medium |
| **LTX-Video** | 12GB+ | Good | Very Fast |
| **HunyuanVideo** | 14GB+ | Excellent | Slow |
| **Mochi 1** | 16GB+ | Excellent | Slow |

### 4.4 Service Dependencies

```
┌─────────────────────────────────────────────────────┐
│                    ComfyUI                          │
│  (Can run ALL models via custom nodes)              │
├─────────────────────────────────────────────────────┤
│  Image Models    │  Video Models    │  LLM Nodes   │
│  - SD 1.5/XL/3.5 │  - CogVideoX     │  - Ollama    │
│  - FLUX.1        │  - HunyuanVideo  │  - llama.cpp │
│  - Playground    │  - Open-Sora     │              │
└─────────────────────────────────────────────────────┘
```

---

## 5. Installation Guide

### 5.1 Quick Start (Automated)

**Linux:**
```bash
curl -fsSL https://archie.kytranempowerment.com/node/install.sh | bash
```

**Windows (PowerShell as Admin):**
```powershell
irm https://archie.kytranempowerment.com/node/install.ps1 | iex
```

### 5.2 Manual Installation

#### Step 1: Prerequisites

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl

# NVIDIA drivers (if GPU)
sudo apt install -y nvidia-driver-535 nvidia-cuda-toolkit
```

**Windows:**
- Python 3.10+ from python.org
- Git from git-scm.com
- NVIDIA drivers from nvidia.com

#### Step 2: Download Node Client

```bash
# Clone the node client
git clone https://github.com/KytranKatarn/archie-node-client.git
cd archie-node-client

# Or download directly
curl -LO https://archie.kytranempowerment.com/node/archie-node-client.zip
unzip archie-node-client.zip
cd archie-node-client
```

#### Step 3: Run Interactive Installer

```bash
python3 install_interactive.py
```

This will:
1. Detect your hardware
2. Recommend services based on capabilities
3. Install selected services
4. Configure auto-start
5. Register with A.R.C.H.I.E.

#### Step 4: Configure Central Connection

Edit `config.py`:
```python
# For local network
CENTRAL_URL = "http://192.168.1.200:3000"

# For VPN connection
CENTRAL_URL = "http://10.0.0.1:3000"
VPN_ENABLED = True
VPN_CONFIG = "/etc/wireguard/archie.conf"
```

### 5.3 Service-Specific Installation

#### Ollama
```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
winget install Ollama.Ollama

# Pull models
ollama pull llama3.2:3b
ollama pull deepseek-coder-v2:16b
```

#### Foocus
```bash
git clone https://github.com/lllyasviel/Fooocus
cd Fooocus
python -m venv venv
source venv/bin/activate  # Linux
# .\venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Start
python launch.py --listen --port 7865
```

#### ComfyUI
```bash
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
python -m venv venv
source venv/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

# Install manager for easy node installation
cd custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager
cd ..

# Start
python main.py --listen --port 8188
```

---

## 6. VPN Configuration

### 6.1 Overview

Remote nodes connect via WireGuard VPN to `vpn.kytranempowerment.com`.

**Network Layout:**
```
VPN Network: 10.0.0.0/24
- 10.0.0.1 = A.R.C.H.I.E. (Central)
- 10.0.0.2-254 = Remote Nodes
```

### 6.2 VPN Server Setup (Central)

```bash
# Install WireGuard
sudo apt install wireguard

# Generate keys
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key

# Create config
cat > /etc/wireguard/wg0.conf << 'EOF'
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <server-private-key>
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Nodes will be added here
EOF

# Enable and start
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
```

### 6.3 Node VPN Setup (Automatic)

The node installer handles this:

```bash
# During node registration, Bridge generates config
curl -X POST "http://archie.kytranempowerment.com:3000/tools/bridge/api/vpn/generate-config" \
  -H "Content-Type: application/json" \
  -d '{"node_name": "my-gpu-node"}'

# Returns WireGuard config to install
```

### 6.4 DNS Configuration

Add to your DNS provider:
```
vpn.kytranempowerment.com  A     <your-public-ip>
archie.kytranempowerment.com  A  <your-public-ip>
```

---

## 7. Mining Integration

### 7.1 Philosophy

Mining integration is **optional** and designed to:
- Utilize idle GPU time
- Generate passive income
- Not interfere with AI workloads

### 7.2 GPU Scheduling

```
┌────────────────────────────────────────────────────┐
│                  GPU Scheduler                      │
├────────────────────────────────────────────────────┤
│  Priority 1: AI Inference (always preempts)        │
│  Priority 2: AI Training (when scheduled)          │
│  Priority 3: Mining (fills idle time)              │
└────────────────────────────────────────────────────┘

Timeline Example:
00:00 ████████░░░░░░░░░░░░░░░░ AI Request (image gen)
00:05 ░░░░░░░░████████████████ Mining (GPU idle)
00:15 ████░░░░░░░░░░░░░░░░░░░░ AI Request (LLM)
00:16 ░░░░████████████████████ Mining resumes
```

### 7.3 Mining Configuration

```python
# In node config.py
MINING_ENABLED = True
MINING_POOL = "stratum+tcp://pool.kytranempowerment.com:3333"
MINING_WALLET = "RVN_WALLET_ADDRESS"
MINING_WORKER = "{node_name}"

# Scheduling
MINING_ONLY_WHEN_IDLE = True      # Pause for AI requests
MINING_MIN_IDLE_SECONDS = 30      # Wait before starting
MINING_GPU_POWER_LIMIT = 80       # % of TDP when mining
MINING_TEMP_LIMIT = 75            # Stop if GPU > 75°C
```

### 7.4 Integration with Archie Pool

The node can report mining stats to A.R.C.H.I.E.:

```python
# Mining heartbeat includes:
{
    "mining_active": true,
    "hashrate_mh": 45.2,
    "shares_accepted": 1234,
    "shares_rejected": 2,
    "gpu_temp": 68,
    "gpu_power": 180,
    "estimated_daily_rvn": 15.5
}
```

### 7.5 Pool Dashboard Integration

The Archie Pool module shows:
- Per-node hashrate contribution
- Combined network stats
- Estimated earnings
- GPU health across all nodes

---

## 8. Node Management

### 8.1 Registration Flow

```
Node Client                    Bridge                      Database
    │                            │                            │
    ├─── POST /register ────────►│                            │
    │    {hardware, services}    │                            │
    │                            ├─── INSERT node ───────────►│
    │                            │                            │
    │◄─── {node_id, api_key} ────┤                            │
    │                            │                            │
    ├─── POST /heartbeat ───────►│                            │
    │    {health, services}      ├─── UPDATE status ─────────►│
    │                            │                            │
    │    (every 30 seconds)      │                            │
```

### 8.2 Bridge UI Features

- **Nodes Tab**: All registered nodes with status
- **Services Tab**: Which services run where
- **Routing Tab**: See how requests are distributed
- **Mining Tab**: Pool stats and per-node hashrate

### 8.3 Node Health Monitoring

Monitored metrics:
- CPU/RAM/GPU usage
- Service availability (Ollama, Foocus, etc.)
- Network latency to central
- Disk space
- GPU temperature
- Mining hashrate (if enabled)

### 8.4 Auto-Recovery

The node client handles:
- Service crash → auto-restart
- VPN disconnect → auto-reconnect
- Central unreachable → local queue
- GPU overheat → pause mining

---

## 9. Troubleshooting

### Node Won't Connect

```bash
# Check connectivity
ping 192.168.1.200  # or VPN IP

# Check VPN
sudo wg show

# Check services
systemctl status archie-node
```

### Service Not Detected

```bash
# Check if service is running
curl http://localhost:11434/api/tags  # Ollama
curl http://localhost:7865/docs       # Foocus
curl http://localhost:8188/system_stats  # ComfyUI

# Check ports
netstat -tlnp | grep -E "11434|7865|8188"
```

### GPU Not Recognized

```bash
# NVIDIA
nvidia-smi
nvcc --version

# AMD
rocm-smi
```

### Mining Not Starting

```bash
# Check GPU availability
nvidia-smi -q -d MEMORY

# Check miner process
ps aux | grep -E "kawpow|rvn"

# Check pool connection
curl http://localhost:3333/stats
```

---

## Appendix A: Port Reference

| Service | Default Port | Protocol |
|---------|--------------|----------|
| Ollama | 11434 | HTTP |
| Foocus | 7865 | HTTP |
| ComfyUI | 8188 | HTTP/WS |
| Auto1111 | 7860 | HTTP |
| InvokeAI | 9090 | HTTP |
| vLLM | 8000 | HTTP |
| llama.cpp | 8080 | HTTP |
| LocalAI | 8080 | HTTP |
| Mining Stratum | 3333 | TCP |
| WireGuard VPN | 51820 | UDP |

---

## Appendix B: Environment Variables

```bash
# Core
ARCHIE_CENTRAL_URL=http://192.168.1.200:3000
ARCHIE_NODE_NAME=my-gpu-node
ARCHIE_API_KEY=<from-registration>

# Services
OLLAMA_HOST=http://localhost:11434
FOOOCUS_URL=http://localhost:7865
COMFYUI_URL=http://localhost:8188

# VPN
ARCHIE_VPN_ENABLED=true
ARCHIE_VPN_INTERFACE=wg0

# Mining
ARCHIE_MINING_ENABLED=true
ARCHIE_MINING_POOL=stratum+tcp://pool.kytranempowerment.com:3333
ARCHIE_MINING_WALLET=<rvn-wallet>
```

---

**Next Steps:**
1. Review hardware requirements
2. Run interactive installer
3. Verify services on Bridge dashboard
4. (Optional) Enable mining integration
