import type { RegistryEntry } from "../../shared.ts";
import {
  GPT_5_6_CODEX_CAPABILITIES,
  GPT_5_5_CODEX_CAPABILITIES,
  getCodexDefaultHeaders,
  resolvePublicCred,
} from "../../shared.ts";

/**
 * The Codex model list, and what each model is PRACTICAL FOR.
 *
 * Advertised on /v1/models as the entry's `description`. Claude Code's gateway
 * model discovery renders that field in its model picker - an entry without one
 * reads "From gateway" - and other OpenAI-compatible clients surface it the
 * same way. "GPT 6 Sol (Max)" alone does not tell a caller whether Max is the
 * right pick; these lines do.
 *
 * The reasoning-effort variants inherit their base model's summary and name the
 * effort they run at, so choosing one is an informed choice rather than a
 * guess.
 */
const CODEX_MODELS: RegistryEntry["models"] = [
  // Astra shares GPT-5.6's Codex limits: the live OAuth catalog reports
  // max_context_window=872000 (context_window=272000 is the pricing tier).
  { id: "gpt-6-astra", name: "GPT 6 Astra", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-astra-ultra", name: "GPT 6 Astra (Ultra)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-astra-max", name: "GPT 6 Astra (Max)", ...GPT_5_6_CODEX_CAPABILITIES },
  {
    id: "gpt-6-astra-xhigh",
    name: "GPT 6 Astra (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  {
    id: "gpt-6-astra-high",
    name: "GPT 6 Astra (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  { id: "gpt-6-astra-medium", name: "GPT 6 Astra (Medium)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-astra-low", name: "GPT 6 Astra (Low)", ...GPT_5_6_CODEX_CAPABILITIES },
  // Sol and Luna report the same windows as Astra; the live catalog offers Sol at
  // low..ultra and Luna at low..max, like the GPT-5.6 Sol/Luna split.
  { id: "gpt-6-sol", name: "GPT 6 Sol", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-sol-ultra", name: "GPT 6 Sol (Ultra)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-sol-max", name: "GPT 6 Sol (Max)", ...GPT_5_6_CODEX_CAPABILITIES },
  {
    id: "gpt-6-sol-xhigh",
    name: "GPT 6 Sol (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  {
    id: "gpt-6-sol-high",
    name: "GPT 6 Sol (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  { id: "gpt-6-sol-medium", name: "GPT 6 Sol (Medium)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-sol-low", name: "GPT 6 Sol (Low)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6.1-sol", name: "GPT 6.1 Sol", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6.1-sol-ultra", name: "GPT 6.1 Sol (Ultra)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6.1-sol-max", name: "GPT 6.1 Sol (Max)", ...GPT_5_6_CODEX_CAPABILITIES },
  {
    id: "gpt-6.1-sol-xhigh",
    name: "GPT 6.1 Sol (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  {
    id: "gpt-6.1-sol-high",
    name: "GPT 6.1 Sol (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  { id: "gpt-6.1-sol-medium", name: "GPT 6.1 Sol (Medium)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6.1-sol-low", name: "GPT 6.1 Sol (Low)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-luna", name: "GPT 6 Luna", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-luna-max", name: "GPT 6 Luna (Max)", ...GPT_5_6_CODEX_CAPABILITIES },
  {
    id: "gpt-6-luna-xhigh",
    name: "GPT 6 Luna (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  {
    id: "gpt-6-luna-high",
    name: "GPT 6 Luna (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    timeoutMs: 1200000,
  },
  { id: "gpt-6-luna-medium", name: "GPT 6 Luna (Medium)", ...GPT_5_6_CODEX_CAPABILITIES },
  { id: "gpt-6-luna-low", name: "GPT 6 Luna (Low)", ...GPT_5_6_CODEX_CAPABILITIES },
  {
    id: "gpt-5.6-sol",
    name: "GPT 5.6 Sol",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-sol-ultra",
    name: "GPT 5.6 Sol (Ultra)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-sol-max",
    name: "GPT 5.6 Sol (Max)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-sol-xhigh",
    name: "GPT 5.6 Sol (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-sol-high",
    name: "GPT 5.6 Sol (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-sol-medium",
    name: "GPT 5.6 Sol (Medium)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-sol-low",
    name: "GPT 5.6 Sol (Low)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-terra",
    name: "GPT 5.6 Terra",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-terra-ultra",
    name: "GPT 5.6 Terra (Ultra)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-terra-max",
    name: "GPT 5.6 Terra (Max)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-terra-xhigh",
    name: "GPT 5.6 Terra (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-terra-high",
    name: "GPT 5.6 Terra (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-terra-medium",
    name: "GPT 5.6 Terra (Medium)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-terra-low",
    name: "GPT 5.6 Terra (Low)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-luna",
    name: "GPT 5.6 Luna",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-luna-max",
    name: "GPT 5.6 Luna (Max)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-luna-xhigh",
    name: "GPT 5.6 Luna (xHigh)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-luna-high",
    name: "GPT 5.6 Luna (High)",
    ...GPT_5_6_CODEX_CAPABILITIES,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.6-luna-medium",
    name: "GPT 5.6 Luna (Medium)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  {
    id: "gpt-5.6-luna-low",
    name: "GPT 5.6 Luna (Low)",
    ...GPT_5_6_CODEX_CAPABILITIES,
  },
  // gpt-5.5 codex OAuth backend caps context at 400K (not the public-API
  // 1.05M). Public refs : openai/codex#19208, #19319, #19464 ;
  // opencode#24171. max_output_tokens is stripped server-side
  // (litellm#21193, codex#4138) so 128K is informational only.
  // The usable INPUT budget is smaller than the 400K window (part is
  // reserved for output), so max_input_tokens must be distinct from
  // context_length or coding agents never auto-compact (#6191). OpenAI's
  // own live catalog reports ~272K for gpt-5.5 in Codex.
  {
    id: "gpt-5.5",
    name: "GPT 5.5",
    ...GPT_5_5_CODEX_CAPABILITIES,
    contextLength: 400000,
    // #6191: input cap per reporter; TODO confirm exact value
    maxInputTokens: 272000,
    maxOutputTokens: 128000,
  },
  {
    id: "gpt-5.5-xhigh",
    name: "GPT 5.5 (xHigh)",
    ...GPT_5_5_CODEX_CAPABILITIES,
    contextLength: 400000,
    // #6191: input cap per reporter; TODO confirm exact value
    maxInputTokens: 272000,
    maxOutputTokens: 128000,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.5-high",
    name: "GPT 5.5 (High)",
    ...GPT_5_5_CODEX_CAPABILITIES,
    contextLength: 400000,
    // #6191: input cap per reporter; TODO confirm exact value
    maxInputTokens: 272000,
    maxOutputTokens: 128000,
    // #6354: reasoning-heavy tier — more header-wait room than the global default.
    timeoutMs: 1200000,
  },
  {
    id: "gpt-5.5-medium",
    name: "GPT 5.5 (Medium)",
    ...GPT_5_5_CODEX_CAPABILITIES,
    contextLength: 400000,
    // #6191: input cap per reporter; TODO confirm exact value
    maxInputTokens: 272000,
    maxOutputTokens: 128000,
  },
  {
    id: "gpt-5.5-low",
    name: "GPT 5.5 (Low)",
    ...GPT_5_5_CODEX_CAPABILITIES,
    contextLength: 400000,
    // #6191: input cap per reporter; TODO confirm exact value
    maxInputTokens: 272000,
    maxOutputTokens: 128000,
  },
];

const CODEX_MODEL_SUMMARIES: Record<string, string> = {
  "gpt-6-astra":
    "GPT 6 Astra - the most capable Codex model. Best for hard multi-step engineering: architecture, large refactors, and problems where you want the deepest reasoning it will do",
  "gpt-6-sol":
    "GPT 6 Sol - the everyday Codex workhorse. Strong at code and reasoning without the top-end latency of Astra; a good default for most coding work",
  "gpt-6.1-sol":
    "GPT 6.1 Sol - a later Sol revision, same shape with a newer training cut. Often better at following a long, precise specification",
  "gpt-6-luna":
    "GPT 6 Luna - fast and capable. The pick for iterative work where you want a quick answer each turn: autocomplete, small edits, exploration",
  "gpt-5.6-sol":
    "GPT 5.6 Sol - the previous generation of Sol. Still good at code and reasoning, and often the more predictable of the two when you are comparing results",
  "gpt-5.6-terra":
    "GPT 5.6 Terra - a very large context window. Useful when everything has to fit at once: a big repository, a long document, a lot of tool output",
  "gpt-5.6-luna":
    "GPT 5.6 Luna - the previous generation of the fast tier. Good for quick iterations at a lower cost than the current models",
  "gpt-5.5":
    "GPT 5.5 - the oldest model still in the catalog. Reliable and cheap; use it when you want a stable baseline rather than the best answer",
};

const CODEX_EFFORT_SUFFIXES = ["ultra", "max", "xhigh", "high", "medium", "low"] as const;

function withCodexModelDescriptions(models: RegistryEntry["models"]): RegistryEntry["models"] {
  return models.map((model) => {
    const effort = CODEX_EFFORT_SUFFIXES.find((suffix) => model.id.endsWith(`-${suffix}`));
    const baseId = effort ? model.id.slice(0, -(effort.length + 1)) : model.id;
    const summary = CODEX_MODEL_SUMMARIES[baseId];
    if (!summary) return model;
    const label =
      effort === "xhigh" ? "xHigh" : effort ? effort[0].toUpperCase() + effort.slice(1) : null;
    return {
      ...model,
      description: label ? `${summary}. Reasoning effort: ${label}.` : `${summary}.`,
    };
  });
}

export const codexProvider: RegistryEntry = {
  id: "codex",
  alias: "cx",
  format: "openai-responses",
  executor: "codex",
  // Codex /responses is upstream-streaming even when the client requested stream:false.
  // Mark it forceStream so chatCore drains terminal SSE into JSON instead of waiting for EOF.
  forceStream: true,
  baseUrl: "https://chatgpt.com/backend-api/codex/responses",
  reasoningTransport: "opaque",
  authType: "oauth",
  authHeader: "bearer",
  defaultContextLength: 400000,
  headers: getCodexDefaultHeaders(),
  oauth: {
    clientIdEnv: "CODEX_OAUTH_CLIENT_ID",
    clientIdDefault: resolvePublicCred("codex_id"),
    clientSecretEnv: "CODEX_OAUTH_CLIENT_SECRET",
    clientSecretDefault: "",
    tokenUrl: "https://auth.openai.com/oauth/token",
  },
  models: withCodexModelDescriptions(CODEX_MODELS),
};
