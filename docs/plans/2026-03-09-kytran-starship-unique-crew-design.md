# KYTRAN-StarShip Unique Crew — Design Doc

**Date**: 2026-03-09
**Status**: Approved
**Related**: Project #124 (Agent Profiles + Model Catalog)

---

## Overview

Replace the 9 cloned hub agents on KYTRAN-StarShip with 6 unique, node-native agents. Each agent has a distinct LLM, character, and role. Enable ComfyUI for image/video generation.

## Fleet Rule

**Every agent across the entire fleet (hub + all nodes) must use a unique LLM model.** No two agents share the same model. Enforced at agent creation.

## Hardware: KYTRAN-StarShip

- GPU: NVIDIA GeForce RTX 3070 (8GB VRAM)
- CPU: Intel i9-12900K (16 cores)
- RAM: 32GB
- OS: Windows 11 Pro
- Constraint: 1 model active in VRAM at a time, others swap to RAM

---

## The Crew (6 Agents)

### 1. Forge — Riku Tanaka (Japanese)
- **Model**: `starcoder2:7b` (4.0GB)
- **Title**: Lead Software Engineer
- **Stations**: ENGINEERING
- **Bio**: Methodical polyglot coder. Approaches every problem like crafting a blade — precise cuts, no wasted motion. Specializes in multi-language codebases and system integration.
- **Worker Type**: internal

### 2. Compass — Amira Hassan (Egyptian)
- **Model**: `aya:8b` (4.9GB)
- **Title**: Operations & Strategy Lead
- **Stations**: OPERATIONS, COMMAND
- **Bio**: Natural coordinator with global perspective. Manages platform operations, SaaS modules, and cross-team planning. Her multilingual capability makes her the node's diplomat.
- **Worker Type**: internal

### 3. Quill — Soren Lindberg (Swedish)
- **Model**: `dolphin3:latest` (4.9GB)
- **Title**: Creative Director
- **Stations**: CREATIVE, COMMUNICATIONS
- **Bio**: Unconventional thinker who thrives on ideation and storytelling. Handles content creation, copywriting, brainstorming, and communications. Pushes creative boundaries.
- **Worker Type**: internal

### 4. Pulse — Yuki Okafor (Nigerian-Japanese)
- **Model**: `deepseek-r1:7b` (4.7GB)
- **Title**: Research Analyst
- **Stations**: RESEARCH, ANALYTICS
- **Bio**: Thinks in chains — breaks complex problems into logical steps. Data analysis, strategic reasoning, and deep research. The crew's problem solver when things get complicated.
- **Worker Type**: internal

### 5. Iris — Lucia Reyes (Filipino)
- **Model**: `llava:latest` (4.7GB) + ComfyUI (gpu_tools)
- **Title**: Visual Media Specialist
- **Stations**: CREATIVE, SUPPORT
- **Bio**: The crew's eyes and canvas. Analyzes images with LLaVA, generates photos and videos through ComfyUI. Handles all visual media for the node — from design mockups to marketing assets.
- **Worker Type**: internal
- **GPU Tools**: `[{provider: "comfyui", type: "image_generation"}]`

### 6. Sentry — Mikhail Volkov (Russian)
- **Model**: `llama3.1:8b` (4.9GB)
- **Title**: Security & QA Lead
- **Stations**: SECURITY, QA
- **Bio**: Vigilant guardian with sharp instincts. Handles testing, monitoring, compliance checks, and IAAE attestation. Trusts nothing until verified — especially his own code.
- **Worker Type**: internal

---

## Model Conflict Check (vs Hub)

| KYTRAN Model | Hub Model | Conflict? |
|---|---|---|
| starcoder2:7b | — | None |
| aya:8b | — | None |
| dolphin3:latest | — | None |
| deepseek-r1:7b | — | None |
| llava:latest | — | None |
| llama3.1:8b | — | None |

Hub models in use: smollm2:1.7b, qwen2.5:1.5b, llama3.2:3b, phi3.5:latest, qwen2.5-coder:7b, mistral:7b, arctic-embed-cpu, qwen25-classify, gemma2:9b, phi4:14b, deepseek-coder-v2:16b, qwen2.5vl:7b, minicpm-v-cpu:latest, gemma3:12b, alpernae/qwen2.5-auditor:latest

Zero overlap confirmed.

---

## Implementation Steps

1. Remove existing 9 cloned hub agents from node_agents (node_id=67)
2. Create 6 new node_agents with hub_agent_id=NULL (node-native)
3. Queue model pulls for all 6 models via mesh_sync_log
4. Enable ComfyUI on node (re-deploy with ComfyUI option)
5. Set gpu_tools on Iris agent
6. Add unique model constraint to agent creation endpoints
7. Total disk needed: ~29GB for all 6 models
