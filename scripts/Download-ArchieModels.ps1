# A.R.C.H.I.E. Optimized Model Download Script (PowerShell)
# Hardware: RTX 3070 (8GB VRAM), i9-12900K, 32GB RAM
# Optimized for VRAM-efficient models with CPU fallback for complex tasks

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "A.R.C.H.I.E. Model Download Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Hardware Profile:" -ForegroundColor Yellow
Write-Host "  GPU: RTX 3070 (8GB VRAM)"
Write-Host "  CPU: i9-12900K (16c/24t)"
Write-Host "  RAM: 32GB"
Write-Host ""
Write-Host "Strategy:" -ForegroundColor Yellow
Write-Host "  - Tier 1: VRAM-fit models (2-5GB) for fast responses"
Write-Host "  - Tier 2: 1-2 larger models (CPU fallback) for complex tasks"
Write-Host ""

# Check if ollama is installed
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaPath) {
    Write-Host "❌ Ollama not found! Please install Ollama first." -ForegroundColor Red
    Write-Host "   Download from: https://ollama.ai" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Ollama detected" -ForegroundColor Green
Write-Host ""

# Function to download with progress
function Download-Model {
    param(
        [string]$Model,
        [string]$Size,
        [string]$Purpose
    )

    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "📦 Downloading: $Model" -ForegroundColor White
    Write-Host "   Size: $Size" -ForegroundColor Gray
    Write-Host "   Purpose: $Purpose" -ForegroundColor Gray
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

    $existingModels = ollama list
    if ($existingModels -match $Model) {
        Write-Host "⏭️  Already downloaded, skipping..." -ForegroundColor Yellow
    } else {
        ollama pull $Model
        Write-Host "✅ $Model downloaded successfully!" -ForegroundColor Green
    }
    Write-Host ""
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "TIER 1: VRAM-Optimized Models (Fast)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "These models fit in 8GB VRAM for maximum speed" -ForegroundColor Gray
Write-Host ""

# Ultra-lightweight for routing/simple tasks
Download-Model -Model "phi3:mini" -Size "2GB" -Purpose "Lightning-fast admin, routing, simple queries"

# Small efficient model
Download-Model -Model "gemma2:2b" -Size "1.6GB" -Purpose "Quick responses, efficient multitasking"

# Creative and conversational
Download-Model -Model "nous-hermes2" -Size "4.1GB" -Purpose "Creative content, sales, customer success"

# Improved general purpose
Download-Model -Model "llama3.1:8b" -Size "4.7GB" -Purpose "General business, HR, operations, healthcare"

Write-Host "✅ Tier 1 Complete!" -ForegroundColor Green
Write-Host "   Total: ~13GB downloaded"
Write-Host "   All models fit in VRAM for fast inference"
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "TIER 2: Complex Reasoning (CPU Fallback)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Larger models for complex tasks (slower but high quality)" -ForegroundColor Gray
Write-Host ""

$response = Read-Host "Download mixtral:8x7b (26GB) for complex reasoning? [y/N]"
if ($response -eq 'y' -or $response -eq 'Y') {
    Download-Model -Model "mixtral:8x7b" -Size "26GB" -Purpose "Legal analysis, complex business decisions"
    Write-Host "ℹ️  Note: This model will use CPU + RAM (slower but excellent quality)" -ForegroundColor Yellow
} else {
    Write-Host "⏭️  Skipping mixtral:8x7b" -ForegroundColor Yellow
}
Write-Host ""

$response = Read-Host "Download command-r (20GB) for RAG/search? [y/N]"
if ($response -eq 'y' -or $response -eq 'Y') {
    Download-Model -Model "command-r" -Size "20GB" -Purpose "Document search, knowledge retrieval"
    Write-Host "ℹ️  Note: This model will use CPU + RAM (slower but excellent for retrieval)" -ForegroundColor Yellow
} else {
    Write-Host "⏭️  Skipping command-r" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "OPTIONAL: Specialized Models" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$response = Read-Host "Download aya:8b (4.9GB) for multilingual support? [y/N]"
if ($response -eq 'y' -or $response -eq 'Y') {
    Download-Model -Model "aya:8b" -Size "4.9GB" -Purpose "Multilingual support (100+ languages)"
} else {
    Write-Host "⏭️  Skipping aya:8b" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ Download Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# Show all downloaded models
Write-Host "📊 All Available Models:" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
ollama list
Write-Host ""

# Memory usage estimates
Write-Host "💾 Estimated VRAM Usage:" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  FITS IN 8GB VRAM (Fast):" -ForegroundColor Green
Write-Host "    • phi3:mini           ~2.0 GB  ⚡"
Write-Host "    • gemma2:2b           ~1.6 GB  ⚡"
Write-Host "    • nous-hermes2        ~4.1 GB  ⚡"
Write-Host "    • llama3.1:8b         ~4.7 GB  ⚡"
Write-Host "    • qwen2.5-coder:7b    ~4.7 GB  ⚡"
Write-Host "    • mistral             ~4.4 GB  ⚡"
Write-Host "    • dolphin3            ~4.9 GB  ⚡"
Write-Host ""
Write-Host "  USES CPU + RAM (Slower):" -ForegroundColor Yellow
Write-Host "    • deepseek-coder-v2:16b  ~8.9 GB  🔄"
Write-Host "    • mixtral:8x7b          ~26 GB    🔄"
Write-Host "    • deepseek-coder:33b    ~18 GB    🔄"
Write-Host ""

Write-Host "🎯 Next Steps:" -ForegroundColor Cyan
Write-Host "1. Test: ollama run llama3.1:8b"
Write-Host "2. Monitor: nvidia-smi"
Write-Host "3. Configure A.R.C.H.I.E. agents"
Write-Host ""
Write-Host "✨ Ready!" -ForegroundColor Green
