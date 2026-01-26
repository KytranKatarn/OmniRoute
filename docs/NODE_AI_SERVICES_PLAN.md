# A.R.C.H.I.E. Node AI Services - Comprehensive Deployment Plan

## Overview

This document outlines the complete AI service deployment strategy for A.R.C.H.I.E. nodes, covering:
- LLM Runners (text generation)
- Text-to-Image generators
- Text-to-Video generators
- Hardware detection and recommendations
- Cross-platform installation (Windows/Linux)

---

## 1. Service Categories

### 1.1 LLM Runners (Text Generation)

| Service | Platform | Min RAM | GPU Required | Best For |
|---------|----------|---------|--------------|----------|
| **Ollama** | Win/Linux/Mac | 8GB | No (GPU helps) | Ease of use, quick setup |
| **llama.cpp** | Win/Linux/Mac | 4GB | No | Edge devices, portability |
| **vLLM** | Linux only | 16GB | Yes (8GB+) | Production, high throughput |
| **LocalAI** | Win/Linux | 8GB | No | OpenAI-compatible API |
| **LM Studio** | Win/Linux/Mac | 8GB | No | GUI-based, beginners |

**Recommendation by Use Case:**
- **Development/Testing**: Ollama (simple) or LM Studio (GUI)
- **Production/High Load**: vLLM (Linux) or Ollama (Windows)
- **Edge/Low Resource**: llama.cpp
- **OpenAI Drop-in**: LocalAI

### 1.2 Text-to-Image Generators

| Service | Platform | Min VRAM | CPU Mode | Best For |
|---------|----------|----------|----------|----------|
| **Foocus** | Win/Linux | 4GB | Slow | Beginners, SDXL |
| **ComfyUI** | Win/Linux | 4GB | Slow | Power users, workflows |
| **Automatic1111** | Win/Linux | 4GB | Slow | Extensions ecosystem |
| **InvokeAI** | Win/Linux | 4GB | Slow | Professional UI |
| **SD.Next** | Win/Linux | 4GB | Slow | Latest models support |

**Supported Models (via any UI):**
- Stable Diffusion 1.5, 2.1, XL, 3.5
- FLUX.1 (Dev/Schnell)
- Playground V2.5
- DeepFloyd IF
- Kandinsky 3.0
- PixArt-α/Σ

### 1.3 Text-to-Video Generators

| Service | Platform | Min VRAM | Quality | Speed |
|---------|----------|----------|---------|-------|
| **Open-Sora 2.0** | Linux (Win partial) | 8GB | Good | Medium |
| **CogVideoX** | Win/Linux | 6GB (INT8) | Good | Fast |
| **HunyuanVideo 1.5** | Linux | 14GB | Excellent | Slow |
| **LTX-Video** | Win/Linux | 12GB | Good | Fast |
| **Mochi 1** | Linux | 16GB+ | Excellent | Slow |
| **Wan 2.1** | Win/Linux | 8GB | Good | Fast |

**Recommendation by Hardware:**
- **6-8GB VRAM**: CogVideoX, Wan 2.1
- **12-16GB VRAM**: LTX-Video, Open-Sora 2.0
- **24GB+ VRAM**: HunyuanVideo, Mochi 1

---

## 2. Hardware Detection & Recommendations

### 2.1 Detection Points

```python
HARDWARE_CHECKS = {
    'cpu': {
        'cores': int,           # Logical cores
        'model': str,           # CPU model name
        'avx2': bool,           # AVX2 support (required for most LLMs)
        'avx512': bool,         # AVX-512 (faster inference)
    },
    'memory': {
        'total_gb': float,      # Total RAM
        'available_gb': float,  # Available RAM
    },
    'gpu': {
        'available': bool,
        'vendor': str,          # nvidia, amd, intel
        'model': str,           # GPU model
        'vram_gb': float,       # VRAM in GB
        'cuda_version': str,    # CUDA version (NVIDIA)
        'rocm_version': str,    # ROCm version (AMD)
        'compute_capability': str,  # CUDA compute capability
    },
    'storage': {
        'free_gb': float,       # Free disk space
        'ssd': bool,            # SSD detected
    },
    'os': {
        'platform': str,        # windows, linux, darwin
        'version': str,         # OS version
        'wsl': bool,            # Running in WSL
        'docker': bool,         # Docker available
    }
}
```

### 2.2 Recommendation Matrix

```python
RECOMMENDATIONS = {
    # No GPU or < 4GB VRAM
    'cpu_only': {
        'llm': ['ollama', 'llama.cpp'],
        'image': [],  # Not recommended
        'video': [],  # Not recommended
        'note': 'Image/video generation requires GPU'
    },

    # 4-6GB VRAM
    'low_vram': {
        'llm': ['ollama', 'llama.cpp'],
        'image': ['foocus', 'comfyui'],
        'video': ['cogvideox'],
        'note': 'Use smaller models, INT8 quantization'
    },

    # 8-12GB VRAM
    'mid_vram': {
        'llm': ['ollama', 'vllm'],
        'image': ['foocus', 'comfyui', 'auto1111'],
        'video': ['open-sora', 'wan21', 'cogvideox'],
        'note': 'Good for most use cases'
    },

    # 16-24GB VRAM
    'high_vram': {
        'llm': ['ollama', 'vllm'],
        'image': ['comfyui', 'auto1111', 'invokeai'],
        'video': ['hunyuanvideo', 'ltx-video', 'mochi'],
        'note': 'Full capability, larger models'
    },

    # 24GB+ VRAM (Professional)
    'professional': {
        'llm': ['vllm', 'ollama'],
        'image': ['comfyui'],  # With FLUX, SD3.5
        'video': ['hunyuanvideo', 'mochi', 'open-sora'],
        'note': 'Production quality, all models supported'
    }
}
```

---

## 3. Installation Scripts Structure

### 3.1 Directory Structure

```
/mnt/archie_brain/node_client/
├── archie_node.py          # Main daemon
├── config.py               # Configuration
├── health_monitor.py       # Service detection
├── installers/
│   ├── __init__.py
│   ├── base_installer.py   # Abstract base class
│   ├── hardware_detect.py  # Hardware detection
│   ├── recommender.py      # Service recommendations
│   │
│   ├── llm/
│   │   ├── ollama.py       # Ollama installer
│   │   ├── llama_cpp.py    # llama.cpp installer
│   │   ├── vllm.py         # vLLM installer (Linux)
│   │   └── localai.py      # LocalAI installer
│   │
│   ├── image/
│   │   ├── foocus.py       # Foocus installer
│   │   ├── comfyui.py      # ComfyUI installer
│   │   ├── auto1111.py     # Automatic1111 installer
│   │   └── invokeai.py     # InvokeAI installer
│   │
│   └── video/
│       ├── open_sora.py    # Open-Sora installer
│       ├── cogvideox.py    # CogVideoX installer
│       ├── hunyuan.py      # HunyuanVideo installer
│       └── ltx_video.py    # LTX-Video installer
│
├── install.sh              # Linux master installer
├── install.ps1             # Windows master installer
└── install_interactive.py  # Interactive installer with menu
```

### 3.2 Base Installer Interface

```python
class BaseInstaller(ABC):
    """Abstract base for all service installers"""

    name: str                    # Service name
    category: str                # llm, image, video
    platforms: List[str]         # ['windows', 'linux']
    min_vram_gb: float          # Minimum VRAM required
    min_ram_gb: float           # Minimum RAM required
    disk_space_gb: float        # Disk space needed
    default_port: int           # Default service port

    @abstractmethod
    def check_requirements(self, hardware: dict) -> Tuple[bool, str]:
        """Check if hardware meets requirements"""
        pass

    @abstractmethod
    def install(self, options: dict) -> bool:
        """Install the service"""
        pass

    @abstractmethod
    def configure(self, options: dict) -> bool:
        """Configure after installation"""
        pass

    @abstractmethod
    def verify(self) -> bool:
        """Verify installation works"""
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """Get current service status"""
        pass
```

---

## 4. Service Specifications

### 4.1 Ollama (LLM)

```yaml
name: Ollama
category: llm
platforms: [windows, linux, darwin]
requirements:
  min_ram_gb: 8
  min_vram_gb: 0  # CPU mode supported
  disk_gb: 10  # Base, models extra

installation:
  linux: |
    curl -fsSL https://ollama.com/install.sh | sh
    systemctl enable ollama
    systemctl start ollama

  windows: |
    winget install Ollama.Ollama
    # Or download from https://ollama.com/download/windows

default_models:
  - llama3.2:3b      # 2GB, general purpose
  - deepseek-coder-v2:16b  # 9GB, coding
  - mistral:7b       # 4GB, fast general
  - phi3:mini        # 2GB, efficient

ports:
  api: 11434

health_check:
  endpoint: /api/tags
  method: GET
```

### 4.2 Foocus (Image)

```yaml
name: Foocus
category: image
platforms: [windows, linux]
requirements:
  min_ram_gb: 8
  min_vram_gb: 4
  disk_gb: 20  # With models

installation:
  linux: |
    git clone https://github.com/lllyasviel/Fooocus
    cd Fooocus
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

  windows: |
    git clone https://github.com/lllyasviel/Fooocus
    cd Fooocus
    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt

ports:
  api: 7865

health_check:
  endpoint: /docs
  method: GET
```

### 4.3 ComfyUI (Image)

```yaml
name: ComfyUI
category: image
platforms: [windows, linux]
requirements:
  min_ram_gb: 8
  min_vram_gb: 4
  disk_gb: 30

installation:
  linux: |
    git clone https://github.com/comfyanonymous/ComfyUI
    cd ComfyUI
    python -m venv venv
    source venv/bin/activate
    pip install torch torchvision torchaudio
    pip install -r requirements.txt

  windows: |
    # Download portable from releases
    # Or use git clone method

ports:
  web: 8188

health_check:
  endpoint: /system_stats
  method: GET
```

### 4.4 Open-Sora (Video)

```yaml
name: Open-Sora
category: video
platforms: [linux]  # Windows via WSL
requirements:
  min_ram_gb: 16
  min_vram_gb: 8
  disk_gb: 50

installation:
  linux: |
    git clone https://github.com/hpcaitech/Open-Sora
    cd Open-Sora
    pip install -e .
    # Download models from HuggingFace

ports:
  gradio: 7860

notes:
  - Requires CUDA 11.8+
  - Best with 16GB+ VRAM
  - Use ComfyUI nodes for easier workflow
```

### 4.5 CogVideoX (Video)

```yaml
name: CogVideoX
category: video
platforms: [windows, linux]
requirements:
  min_ram_gb: 16
  min_vram_gb: 6  # With INT8
  disk_gb: 30

installation:
  all: |
    pip install diffusers transformers accelerate
    # Models auto-download from HuggingFace

models:
  - CogVideoX-2B     # 6GB VRAM
  - CogVideoX-5B     # 12GB VRAM
  - CogVideoX1.5-5B  # 12GB VRAM, better quality

notes:
  - INT8 quantization available
  - ComfyUI nodes available
```

---

## 5. Database Schema Updates

### 5.1 New Columns for remote_nodes

```sql
-- Add video generation service columns
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS opensora_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS opensora_port INTEGER DEFAULT 7860;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS cogvideox_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS hunyuan_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS ltxvideo_available BOOLEAN DEFAULT FALSE;

-- Add LLM runner alternatives
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS llama_cpp_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS llama_cpp_port INTEGER DEFAULT 8080;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS vllm_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS vllm_port INTEGER DEFAULT 8000;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS localai_available BOOLEAN DEFAULT FALSE;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS localai_port INTEGER DEFAULT 8080;

-- Hardware capabilities for recommendations
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS cuda_version VARCHAR(20);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS rocm_version VARCHAR(20);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS avx2_support BOOLEAN DEFAULT FALSE;
```

---

## 6. Implementation Phases

### Phase 1: Enhanced Hardware Detection
- [ ] Update health_monitor.py with full hardware detection
- [ ] Add CUDA/ROCm version detection
- [ ] Add AVX2/AVX-512 detection
- [ ] Add disk space and SSD detection

### Phase 2: Installer Framework
- [ ] Create base_installer.py abstract class
- [ ] Create hardware_detect.py module
- [ ] Create recommender.py for service suggestions
- [ ] Implement Ollama installer (reference)

### Phase 3: Image Service Installers
- [ ] Foocus installer
- [ ] ComfyUI installer
- [ ] Auto1111 installer
- [ ] InvokeAI installer

### Phase 4: Video Service Installers
- [ ] CogVideoX installer (easiest)
- [ ] Open-Sora installer
- [ ] LTX-Video installer
- [ ] HunyuanVideo installer (advanced)

### Phase 5: Alternative LLM Runners
- [ ] llama.cpp installer
- [ ] vLLM installer (Linux)
- [ ] LocalAI installer

### Phase 6: Interactive Installer
- [ ] Create install_interactive.py with menu
- [ ] Hardware analysis and recommendations
- [ ] One-click installation of recommended services
- [ ] Service verification and testing

### Phase 7: Bridge Integration
- [ ] Update node_router.py for new services
- [ ] Add video generation routing
- [ ] Add LLM runner routing (failover)
- [ ] Update Bridge UI to show all services

---

## 7. Sources

- [Stable Diffusion Alternatives (DigitalOcean)](https://www.digitalocean.com/resources/articles/stable-diffusion-alternatives)
- [Open-Source AI Image Generators (Pinggy)](https://pinggy.io/blog/best_free_open_source_ai_image_generators_to_self_host/)
- [Open-Source Video Generation Models (Pixazo)](https://www.pixazo.ai/blog/best-open-source-ai-video-generation-models)
- [Open-Sora GitHub](https://github.com/hpcaitech/Open-Sora)
- [Ollama Alternatives Guide (LocalLLM)](https://localllm.in/blog/complete-guide-ollama-alternatives)
- [vLLM vs Ollama vs llama.cpp (ITECS)](https://itecsonline.com/post/vllm-vs-ollama-vs-llama.cpp-vs-tgi-vs-tensort)
- [Local LLM Hosting Guide 2025](https://www.glukhov.org/post/2025/11/hosting-llms-ollama-localai-jan-lmstudio-vllm-comparison/)

---

**Last Updated**: 2026-01-22
**Status**: Planning Phase
