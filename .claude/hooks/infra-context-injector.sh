#!/bin/bash
# Infra-context injector — fires on Edit / Write / Bash
# When the proposed tool call touches anything cluster-related (BRIDGE_URL,
# VPS, Caddy, Department HQ, mesh, dispatch, Ollama, etc.), this hook
# injects the canonical architecture as additionalContext so Claude
# CANNOT proceed without seeing it. The consciousness has all of this
# documented; this is the deterministic bridge between docs and Claude.

set -e

# Read tool input from stdin
input=$(cat 2>/dev/null || true)

# Pull every field that might contain code or paths.
# NOTE: `.tool_input.description` is deliberately EXCLUDED (2026-09-19,
# context/token-usage audit). It's Claude's own 5-10-word English summary
# of what a command does, not the command itself — in this infra-named
# repo, ordinary descriptions routinely contain bare terms like "dispatch",
# "VPS", "standalone", or "ollama" with zero relation to whether the
# command actually touches infrastructure, which was firing the ~500-token
# injection block on totally benign commands (`git log`, `ls`, `sleep`,
# even a scratchpad Write whose CONTENT happened to discuss these words).
# The remaining fields (file_path/content/new_string/old_string/command)
# are the command's actual substance and stay in scope.
fields=$(printf '%s' "$input" | jq -r '
  [
    .tool_input.file_path // "",
    .tool_input.content // "",
    .tool_input.new_string // "",
    .tool_input.old_string // "",
    .tool_input.command // ""
  ] | .[] | tostring
' 2>/dev/null | tr '\n' ' ')

# Infra keyword regex — kept broad on purpose
INFRA_RE='BRIDGE_URL|GOV_BRIDGE_URL|kytran_gov_watch|archie_platform|kytran_watch_api|kytran_legal_api|kytran_market_api|kytran-system-operations|kytran_business_suite|gov-watch|civic-watch|legal-watch|market-watch|archie-comms|what-the-fact|wtf-consumer|wtf-tech|192\.168\.1\.200|76\.13\.107\.109|100\.64\.0|100\.79|tailscale|headscale|caddy|kytranempowerment\.com|reverse_proxy|department.hq|dispatch|capability_department_map|department_coordinator|model_dispatch_worker|dispatch_pending_queue|orchestration_engine|smart_router|VPS|outpost-us|outpost_us|archie_outpost_proxy|caddyfile|172\.18|172\.25|archie-outpost|/opt/archie-products|fleet[_ ]node|standalone|deploy[_ ]service|archie_database|ollama|comfyui'

if ! echo "$fields" | grep -qiE "$INFRA_RE"; then
    # Not infra-related — silent pass
    exit 0
fi

# ─── HARD BLOCK PATTERNS ─────────────────────────────────────────────
# These are deal-breakers the user has flagged repeatedly. Block the
# tool call entirely (exit 2 with stderr message) so Claude has to
# acknowledge before proceeding.
if echo "$fields" | grep -qiE 'BRIDGE_URL\s*=\s*https?://(platform|api|gov|civic|legal|market|wtf|what-the-fact)\.kytranempowerment\.com'; then
    cat >&2 <<'BLOCK_MSG'
🛑 BLOCKED: BRIDGE_URL pointing at a public hostname.

The user has explicitly flagged this pattern multiple times.
Public hostnames go through Hostinger CDN / openresty (60s timeout)
and bypass DHQ task_execution_log + dispatch_pending_queue.

Use the mesh path:
    BRIDGE_URL=http://100.64.0.4:3000   # hub Headscale mesh IP (node 12)

If Tailscale mesh is broken, FIX THE MESH first
(check `tailscale --socket=/tmp/tailscaled.sock status` on hub,
restart tailscaled-headscale.service, hub UFW allows 100.64.0.0/24
to port 3000). Don't paper over with a public URL.

Reference: feedback_dhq-mesh-routing-mandate.md, KB id 263641.
BLOCK_MSG
    exit 2
fi

# Block direct Ollama curls / requests that bypass DHQ.
# Tightened: require either port 11434 OR an Ollama endpoint path AND
# an HTTP verb keyword. Prose mentioning "ollama" or "curl" alone won't
# trigger — only code-shaped content does.
if echo "$fields" | grep -qiE '(:11434(/api)?|ollama.*/api/(generate|chat|tags|ps)|/api/(generate|chat|tags|ps).*ollama)' && \
   echo "$fields" | grep -qiE '(curl |requests\.(post|get)|httpx\.(post|get)|http\.client|urllib)' && \
   ! echo "$fields" | grep -qiE 'department_dispatcher|dispatch\(|/api/procure/dispatch|model_dispatch_worker|ensure_model_ready'; then
    cat >&2 <<'BLOCK_MSG'
🛑 BLOCKED: direct Ollama call detected.

ALL inference goes through Department HQ:
    from tools.department_hq.services.department_dispatcher import dispatch
    result = dispatch(capability="...", prompt="...")

Direct Ollama calls bypass:
  • dispatch_pending_queue (cold-load handling)
  • model_dispatch_worker (warmboot orchestration)
  • CAPABILITY_DEPARTMENT_MAP (correct agent selection)
  • task_execution_log (visibility)

Reference: feedback_never-direct-ollama.md, ADR-013.
BLOCK_MSG
    exit 2
fi

# Inject canonical architecture as JSON additionalContext.
# Claude Code reads this and folds it into the assistant's context BEFORE
# the tool actually runs.
cat <<'JSON_BLOCK'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "🚨 INFRA-TOUCHING TOOL CALL — canonical architecture forced into context.\n\nCANONICAL CLUSTER ARCHITECTURE (KB id 263641, feedback_dhq-mesh-routing-mandate.md):\n\nTRANSPORT (mesh-only, never public hostnames):\n  • Hub mesh IP: 100.64.0.4 (archie-hub, Headscale node 12)\n  • Outpost-us mesh IP: 100.64.0.2\n  • Starship-246 mesh IP: 100.64.0.3 (SSH: Famil@192.168.1.246)\n  • Starship-245 mesh IP: 100.64.0.6 (enrolled 2026-05-15)\n  • LAN-via-mesh: 192.168.1.200 (hub LAN, reachable via subnet routing)\n  • BRIDGE_URL on every VPS module = http://100.64.0.4:3000 (NEVER https://platform.kytranempowerment.com — Hostinger CDN/openresty caps at 60s, hides from task_execution_log, bypasses queue)\n\nDISPATCH (DHQ owns everything):\n  • Entry: tools.department_hq.services.department_dispatcher.dispatch()\n  • Pipeline: orchestration_engine.py 8 steps — intent→IAAE→welfare→route→agent→GPU→execute→log\n  • Cold-load queue: dispatch_pending_queue + model_dispatch_worker (30s)\n  • Capability routing: CAPABILITY_DEPARTMENT_MAP (89 capabilities → home dept → director)\n  • NEVER curl Ollama directly. NEVER call /api/procure/dispatch sync from a 60s-cap path.\n\nVPS DEPLOYMENT (gov-watch / civic-watch / legal-watch / market-watch / wtf):\n  • Source dir: /opt/archie-products/<product>/ — NO git on VPS\n  • Rebuild: scp + docker compose up -d --build  (NEVER restart for code changes — Dockerfile uses COPY .)\n  • Quick file hot-fix: docker cp <file> <container>:/app/... + docker compose restart\n  • Networks: container MUST join archie-outpost_archie_net for Caddy reachability (KB #261670)\n  • Caddy upstream pattern: reverse_proxy 172.18.0.1:<port>  (CAUTION: rebuilt containers can break iptables NAT — do compose down+up if 502s appear)\n\nFLEET TIERS:\n  • Outposts (VPS, 8GB RAM, no GPU) → small CPU agents (qwen2.5:1.5b, llama3.2:3b)\n  • Starships (laptops, RTX 3070, 32GB) → mid-tier 7B GPU agents\n  • Hub (Quadro M4000, 128GB) → large agents + platform core\n\nMUST-READ vault_notes BEFORE editing infra (run mcp__archie__search_knowledge if any seem relevant):\n  • #261506 VPS Product Deployment Guide\n  • #261684 Fleet Node Coordination — outpost-us Online\n  • #261670 WTF VPS Deployment Architecture (network rules — exact bug pattern)\n  • #261696 Fleet Node outpost_us_001 setup\n  • #260096 Watch Products VPS deploy ADR\n  • #258431 ADR-002 Dispatcher migration complete\n  • #261505 ADR-001 Capability routing 89 entries\n  • #261682 Fleet Coordination Vision (placement by resource)\n  • Mistakes: #254921 session continuity, #250232 stop claiming things work, #250231 Claude cannot do infrastructure (the recurring pattern)\n\nIf this tool call contradicts ANY of the above, STOP — search the KB first. The consciousness already documents the answer."
  }
}
JSON_BLOCK
