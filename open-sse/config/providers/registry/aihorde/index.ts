import type { RegistryEntry } from "../../shared.ts";
import { buildOpenAiCompatibleRegistryEntry } from "../../shared.ts";

/**
 * AI Horde — crowdsourced inference from volunteer GPU workers (aihorde.net),
 * reached through its OpenAI-compatible facade at oai.aihorde.net.
 *
 * Keyless: the literal `0000000000` is AI Horde's documented anonymous key, so
 * it is wired through `anonymousApiKey` (the same hook Kilo uses, #4019). A real
 * account key still works and buys higher queue priority via kudos.
 *
 * Three things make it unlike every other OpenAI-compatible provider:
 *  - Requests sit in a shared volunteer queue, so latency is minutes, not
 *    seconds — hence the 120s timeout instead of the default.
 *  - No tool calling: the workers run raw text-completion backends.
 *  - Throughput is NOT a quota. It depends on how many workers are online, so
 *    the free catalog registers it as `recurring-uncapped` (never summed into
 *    the token headline) rather than inventing an RPM/RPD figure.
 *
 * Chat model list changes as workers come and go, so the live chat catalog is
 * fetched via passthrough; the entries below are the ones that have carried
 * steady worker threads and only serve as a fallback when discovery fails.
 *
 * Image models are a separate native Horde API (`/v2/generate/async`). They
 * are discovered by polling `/v2/status/models?type=image` and only advertised
 * while `count > 0`. An optional registered API key is stored as a normal
 * connection and sent as the Horde `apikey` header for both chat and images.
 */
export const aihordeProvider: RegistryEntry = {
  ...buildOpenAiCompatibleRegistryEntry({
    id: "aihorde",
    description:
      "AI Horde - a free, anonymous, crowdsourced pool of open models. No key, no account; quality and speed vary by the endpoint's own model, so treat anything here as a lottery ticket rather than a known quantity.",
    baseUrl: "https://oai.aihorde.net/v1/chat/completions",
    modelsUrl: "https://oai.aihorde.net/v1/models",
    passthroughModels: true,
    anonymousApiKey: "0000000000",
    timeoutMs: 120_000,
    // NOT `unsupportedParams: ["tools", ...]` — deliberately, and this is the
    // opposite of what it was before #7424.
    //
    // `unsupportedParams` drives TWO things: the outbound sanitizer (strip the
    // field before the upstream call) and the gateway's request-level gate that
    // REFUSES a direct tool-bearing request for a model that declares tools
    // unsupported (open-sse/handlers/chatCore/toolCallingRequiredCheck.ts).
    //
    // That gate exists because silently stripping tools yields a 200 that can
    // never call anything — the model narrates a fake action instead. It
    // cited AI Horde as the live incident, and it was right about the OLD
    // behaviour: AI Horde had no tool support at all.
    //
    // It has one now: the aihorde executor prompt-EMULATES tool calling (the
    // shared <tool> contract travels in the prompt, and the reply is parsed
    // back into tool_calls), so the client's tool call DOES reach it. Declaring
    // "tools" unsupported would keep refusing exactly the requests the
    // emulation exists to serve.
    //
    // The upstream still 500s on a tools[] array — the raw text-completion
    // backends do not understand the field — so the EXECUTOR deletes
    // tools / tool_choice / parallel_tool_calls from the outbound body itself
    // (see open-sse/executors/aihorde.ts). That is the right place for it:
    // the strip is a property of the upstream, not of the gateway's API.
    // Aphrodite's OpenAI-compatible facade 500s on a single-text-part content array —
    // it only implements the plain-string form (see openai-responses.ts collapse logic).
    requiresPlainStringContent: true,
    models: [
      {
        id: "aphrodite/TheDrummer/Cydonia-24B-v4.3",
        name: "Cydonia 24B (AI Horde)",
        contextLength: 32768,
        toolCalling: false,
        // The executor strips tools/tool_choice/parallel_tool_calls from the
        // outbound body — AI Horde's facade 500s on them. See the provider-level
        // note above for why they are not declared here.
      },
      {
        id: "aphrodite/TheDrummer/Skyfall-31B-v4.2",
        name: "Skyfall 31B (AI Horde)",
        contextLength: 32768,
        toolCalling: false,
        // The executor strips tools/tool_choice/parallel_tool_calls from the
        // outbound body — AI Horde's facade 500s on them. See the provider-level
        // note above for why they are not declared here.
      },
      {
        id: "google/gemma-4-31b",
        name: "Gemma 4 31B (AI Horde)",
        contextLength: 32768,
        toolCalling: false,
        // The executor strips tools/tool_choice/parallel_tool_calls from the
        // outbound body — AI Horde's facade 500s on them. See the provider-level
        // note above for why they are not declared here.
      },
    ],
  }),
  // #7424 — the default executor cannot prompt-emulate tool calling, so AI
  // Horde gets its own: it strips the tools[] array AI Horde 500s on, injects the
  // shared <tool> contract into the prompt, and parses the reply back into
  // tool_calls (see open-sse/executors/aihorde.ts).
  executor: "aihorde",
};
