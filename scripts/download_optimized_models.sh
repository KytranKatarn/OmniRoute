#!/bin/bash
# A.R.C.H.I.E. Optimized Model Download Script
# Hardware: RTX 3070 (8GB VRAM), i9-12900K, 32GB RAM
# Optimized for VRAM-efficient models with CPU fallback for complex tasks

set -e

echo "=========================================="
echo "A.R.C.H.I.E. Model Download Script"
echo "=========================================="
echo ""
echo "Hardware Profile:"
echo "  GPU: RTX 3070 (8GB VRAM)"
echo "  CPU: i9-12900K (16c/24t)"
echo "  RAM: 32GB"
echo ""
echo "Strategy:"
echo "  - Tier 1: VRAM-fit models (2-5GB) for fast responses"
echo "  - Tier 2: 1-2 larger models (CPU fallback) for complex tasks"
echo ""

# Check if ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found! Please install Ollama first."
    echo "   Download from: https://ollama.ai"
    exit 1
fi

echo "✅ Ollama detected"
echo ""

# Function to download with progress
download_model() {
    local model=$1
    local size=$2
    local purpose=$3

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📦 Downloading: $model"
    echo "   Size: $size"
    echo "   Purpose: $purpose"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if ollama list | grep -q "^$model"; then
        echo "⏭️  Already downloaded, skipping..."
    else
        ollama pull "$model"
        echo "✅ $model downloaded successfully!"
    fi
    echo ""
}

echo "=========================================="
echo "TIER 1: VRAM-Optimized Models (Fast)"
echo "=========================================="
echo "These models fit in 8GB VRAM for maximum speed"
echo ""

# Ultra-lightweight for routing/simple tasks
download_model "phi3:mini" "2GB" "Lightning-fast admin, routing, simple queries"

# Small efficient model
download_model "gemma2:2b" "1.6GB" "Quick responses, efficient multitasking"

# Creative and conversational
download_model "nous-hermes2" "4.1GB" "Creative content, sales, customer success"

# Improved general purpose
download_model "llama3.1:8b" "4.7GB" "General business, HR, operations, healthcare"

# Lightweight coding assistant (if not already have deepseek-coder:latest)
if ! ollama list | grep -q "deepseek-coder:latest"; then
    download_model "deepseek-coder:latest" "776MB" "Lightweight code help"
fi

echo "✅ Tier 1 Complete!"
echo "   Total: ~13GB downloaded"
echo "   All models fit in VRAM for fast inference"
echo ""

echo "=========================================="
echo "TIER 2: Complex Reasoning (CPU Fallback)"
echo "=========================================="
echo "Larger models for complex tasks (slower but high quality)"
echo ""

read -p "Download mixtral:8x7b (26GB) for complex reasoning? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    download_model "mixtral:8x7b" "26GB" "Legal analysis, complex business decisions, strategic planning"
    echo "ℹ️  Note: This model will use CPU + RAM (slower but excellent quality)"
else
    echo "⏭️  Skipping mixtral:8x7b"
fi
echo ""

read -p "Download command-r (20GB) for RAG/search? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    download_model "command-r" "20GB" "Document search, knowledge retrieval, RAG tasks"
    echo "ℹ️  Note: This model will use CPU + RAM (slower but excellent for retrieval)"
else
    echo "⏭️  Skipping command-r"
fi
echo ""

echo "=========================================="
echo "OPTIONAL: Specialized Models"
echo "=========================================="
echo ""

read -p "Download aya:8b (4.9GB) for multilingual support? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    download_model "aya:8b" "4.9GB" "Multilingual support (100+ languages)"
else
    echo "⏭️  Skipping aya:8b"
fi
echo ""

echo "=========================================="
echo "✅ Download Complete!"
echo "=========================================="
echo ""

# Show all downloaded models
echo "📊 All Available Models:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ollama list
echo ""

# Memory usage estimates
echo "💾 Estimated VRAM Usage by Model:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FITS IN 8GB VRAM (Fast):"
echo "    • phi3:mini           ~2.0 GB  ⚡ Ultra-fast"
echo "    • gemma2:2b           ~1.6 GB  ⚡ Ultra-fast"
echo "    • deepseek-coder      ~0.8 GB  ⚡ Ultra-fast"
echo "    • nous-hermes2        ~4.1 GB  ⚡ Fast"
echo "    • llama3.1:8b         ~4.7 GB  ⚡ Fast"
echo "    • qwen2.5-coder:7b    ~4.7 GB  ⚡ Fast"
echo "    • mistral             ~4.4 GB  ⚡ Fast"
echo "    • dolphin3            ~4.9 GB  ⚡ Fast"
echo "    • codellama           ~3.8 GB  ⚡ Fast"
echo ""
echo "  USES CPU + RAM (Slower but capable):"
echo "    • deepseek-coder-v2:16b  ~8.9 GB  🔄 CPU assist"
echo "    • mixtral:8x7b          ~26 GB    🔄 CPU only"
echo "    • command-r             ~20 GB    🔄 CPU only"
echo "    • deepseek-coder:33b    ~18 GB    🔄 CPU only"
echo ""

echo "📝 Usage Tips:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. FAST QUERIES: Use 7B and smaller models (phi3, gemma2, llama3.1, qwen)"
echo "2. COMPLEX TASKS: Use larger models when quality > speed (mixtral, deepseek:33b)"
echo "3. PARALLEL TASKS: Your CPU can handle multiple small models simultaneously"
echo "4. MEMORY: Keep 2-3 models in VRAM, rest will swap as needed"
echo ""

echo "🎯 Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Test a model: ollama run llama3.1:8b"
echo "2. Check memory: nvidia-smi (watch VRAM usage)"
echo "3. Configure A.R.C.H.I.E. agents to use these models"
echo ""

echo "✨ Ready to assign agents to optimal models!"
echo ""
