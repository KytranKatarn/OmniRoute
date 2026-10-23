/**
 * Cloudflare AI Playground — No Auth provider registry entry.
 *
 * Free, anonymous access to the Cloudflare AI Playground
 * (https://playground.ai.cloudflare.com) — no account, no API key, no cookies.
 * Chat runs over a PartySocket WebSocket speaking Cloudflare's `cf_agent`
 * protocol; the only gate is a browser-grade TLS fingerprint on the WS upgrade,
 * which the `cloudflare-playground` executor satisfies by driving a headless
 * Chromium via Playwright (see executors/cloudflare-playground.ts).
 *
 * Model catalog captured from the playground's live `getModels` RPC
 * (2026-08-15, 63 models total; the 20 chat/text-generation entries are listed
 * here). Model IDs use the playground's `org/model` slug form — the executor
 * prefixes them with `@cf/` when talking to the upstream.
 */
import type { RegistryEntry } from "../../shared.ts";

/**
 * The model list, and what each model is PRACTICAL FOR.
 *
 * Advertised on /v1/models as the entry's `description`. Claude Code's gateway
 * model discovery renders that field in its model picker - an entry without one
 * reads "From gateway" - and other OpenAI-compatible clients surface it the
 * same way. A list of bare names is not a menu: it tells a caller nothing
 * about which model to pick, or what each one is actually good at.
 *
 * Each description says what the model is practical for and what it costs
 * (speed, money, or a narrower pool). Keep them to one or two sentences.
 */
const CLOUDFLARE_PLAYGROUND_MODELS: RegistryEntry["models"] = [
  // Frontier/open-weight flagships first.
  { id: "zai-org/glm-5.2", name: "GLM 5.2 (Z.ai)", supportsReasoning: true },
  { id: "moonshotai/kimi-k2.7-code", name: "Kimi K2.7 Code (Moonshot)", supportsReasoning: true },
  { id: "moonshotai/kimi-k2.6", name: "Kimi K2.6 (Moonshot)", supportsReasoning: true },
  {
    id: "deepseek-ai/deepseek-v4-pro-0813",
    name: "DeepSeek V4 Pro (DeepSeek)",
    supportsReasoning: true,
  },
  { id: "deepseek-ai/deepseek-v4-flash-0731", name: "DeepSeek V4 Flash (DeepSeek)" },
  { id: "zai-org/glm-4.7-flash", name: "GLM 4.7 Flash (Z.ai)", supportsReasoning: true },
  { id: "openai/gpt-oss-120b", name: "GPT-OSS 120B (OpenAI)" },
  { id: "openai/gpt-oss-20b", name: "GPT-OSS 20B (OpenAI)" },
  { id: "meta-llama/llama-3.3-70b-instruct-fp8-fast", name: "Llama 3.3 70B Instruct (Meta)" },
  { id: "meta/llama-3.1-8b-instruct-fp8", name: "Llama 3.1 8B Instruct (Meta)" },
  { id: "meta/llama-4-scout-17b-16e-instruct", name: "Llama 4 Scout 17B (Meta)" },
  { id: "nvidia/nemotron-3-120b-a12b", name: "Nemotron 3 120B (NVIDIA)" },
  { id: "qwen/qwen2.5-coder-32b-instruct", name: "Qwen2.5 Coder 32B (Qwen)" },
  { id: "qwen/qwen3-30b-a3b-fp8", name: "Qwen3 30B A3B (Qwen)" },
  { id: "qwen/qwq-32b", name: "QwQ 32B (Qwen)", supportsReasoning: true },
  {
    id: "deepseek-ai/deepseek-r1-distill-qwen-32b",
    name: "DeepSeek R1 Distill Qwen 32B",
    supportsReasoning: true,
  },
  { id: "google/gemma-4-26b-a4b-it", name: "Gemma 4 26B A4B (Google)" },
  { id: "mistralai/mistral-small-3.1-24b-instruct", name: "Mistral Small 3.1 24B" },
  { id: "ibm-granite/granite-4.0-h-micro", name: "Granite 4.0 H Micro (IBM)" },
  { id: "aisingapore/gemma-sea-lion-v4-27b-it", name: "Gemma SEA-LION V4 27B (AI Singapore)" },
];

const withCloudflarePlaygroundDescriptions_DESCRIPTIONS: Record<string, string> = {
  "zai-org/glm-5.2":
    "GLM 5.2 - the strongest model in the free playground set. Good at code, maths and multi-step reasoning. It goes through a browser session, so allow for the latency.",
  "moonshotai/kimi-k2.7-code":
    "Kimi K2.7 Code - code-specialised and long-context. The free set's best pick for large refactors and for reading a whole repository into the window.",
  "moonshotai/kimi-k2.6":
    "Kimi K2.6 - a long-context generalist. Good at code and long documents; a step down from K2.7 Code.",
  "deepseek-ai/deepseek-v4-pro-0813":
    "DeepSeek V4 Pro - strong reasoning and code for a free model. A good default for hard problems when you want depth over speed.",
  "deepseek-ai/deepseek-v4-flash-0731":
    "DeepSeek V4 Flash - the fast, cheap sibling of V4 Pro. Good for routine code edits and quick questions.",
  "zai-org/glm-4.7-flash":
    "GLM 4.7 Flash - a small, quick GLM. Fine for straightforward code and short reasoning chains.",
  "openai/gpt-oss-120b":
    "GPT-OSS 120B - OpenAI's open-weight model at full size. Strong general reasoning, and the most capable of the open-weight models here.",
  "openai/gpt-oss-20b":
    "GPT-OSS 20B - the small, fast sibling. Good for quick edits and routine tasks where the big model is overkill.",
  "meta-llama/llama-3.3-70b-instruct-fp8-fast":
    "Llama 3.3 70B Instruct - a solid general-purpose model: clear writing, dependable code, and good instruction-following.",
  "meta/llama-3.1-8b-instruct-fp8":
    "Llama 3.1 8B Instruct - very small and very fast. Best for autocomplete, formatting and trivial edits; not for hard problems.",
  "meta/llama-4-scout-17b-16e-instruct":
    "Llama 4 Scout 17B - a newer mid-size Llama with good instruction-following. A balanced default when you have no preference.",
  "nvidia/nemotron-3-120b-a12b":
    "Nemotron 3 120B - NVIDIA's large reasoning model. Strong at maths, planning and long structured output; slow.",
  "qwen/qwen2.5-coder-32b-instruct":
    "Qwen 2.5 Coder 32B - built for code: generation, completion and refactoring across languages. The free set's dedicated coder.",
  "qwen/qwen3-30b-a3b-fp8":
    "Qwen3 30B A3B - a fast mixture-of-experts model with a large active parameter count. Good at reasoning and tool use.",
  "qwen/qwq-32b":
    "QwQ 32B - a reasoning-first model that thinks before answering. Good for maths and tricky logic; slower than it needs to be for simple work.",
  "deepseek-ai/deepseek-r1-distill-qwen-32b":
    "DeepSeek R1 Distill (Qwen 32B) - reasoning distilled into a 32B model. Shows its working; good for maths and planning.",
  "google/gemma-4-26b-a4b-it":
    "Gemma 4 26B - Google's open model, instruction-tuned. Well-rounded for writing and everyday tasks.",
  "mistralai/mistral-small-3.1-24b-instruct":
    "Mistral Small 3.1 24B - a compact generalist that follows instructions closely. Good for structured output and short code.",
  "ibm-granite/granite-4.0-h-micro":
    "Granite 4.0 H Micro - IBM's small model, built for grounded, factual answers. Very fast; keep it for lookups and simple questions.",
  "aisingapore/gemma-sea-lion-v4-27b-it":
    "Gemma SEA-LION 27B - a South-East-Asian-tuned Gemma. Strong on regional languages and on translation.",
};

function withCloudflarePlaygroundDescriptions(
  models: RegistryEntry["models"]
): RegistryEntry["models"] {
  return models.map((model) => {
    const description = withCloudflarePlaygroundDescriptions_DESCRIPTIONS[model.id];
    return description ? { ...model, description } : model;
  });
}

export const cloudflarePlaygroundProvider: RegistryEntry = {
  id: "cloudflare-playground",
  alias: "cfp",
  format: "openai",
  executor: "cloudflare-playground",
  baseUrl: "https://playground.ai.cloudflare.com",
  authType: "none",
  authHeader: "none",
  toolCalling: "emulated",
  models: withCloudflarePlaygroundDescriptions(CLOUDFLARE_PLAYGROUND_MODELS),
};
