import { BaseExecutor, type ExecuteInput, type ExecutorExecuteResult } from "./base.ts";
import { PROVIDERS } from "../config/constants.ts";
import { errorResponse } from "../utils/error.ts";
import { prepareToolMessages, buildToolAwareResult } from "../translator/webTools.ts";

/**
 * AihordeExecutor — AI Horde over its plain OpenAI-compatible endpoint.
 *
 * WHY THIS EXISTS (#7424)
 * ----------------------
 * The keyless (free) auto-combo pool had exactly ONE transport with real
 * capacity: `cloudflare-playground`, whose executor keeps a SINGLE Chromium
 * page (`private page: Page | null`) that all forty of its models ride. One
 * browser crash removed 95% of the free tier at once.
 *
 * AI Horde is the only candidate in the catalogue that is free AND genuinely
 * independent: plain HTTPS, no account, no browser, no local CLI, no owner
 * subscription. Measured live 2026-10-22:
 *
 *   POST https://oai.aihorde.net/v1/chat/completions  -> 200, a real completion
 *   GET  https://oai.aihorde.net/v1/models              -> 30 models offered
 *
 * AI Horde has NO native function calling, so its tool calls have to be
 * prompt-emulated — the same shim the web-cookie providers use. The tool
 * contract is injected into the messages by the shared `prepareToolMessages`,
 * and the reply is parsed back out by the shared `buildToolAwareResult`.
 *
 * AI Horde's models answer the contract by naming the tool in its own tag:
 *
 *     <tool>
 *     <get_weather>
 *     {"location": "Toronto"}
 *     </tool>
 *
 * which the shared parser only sees after the named-block normalisation added
 * in translator/webTools.ts (normalizeNamedBlockToolCalls).
 *
 * TWO THINGS AI HORDE IS Fussy ABOUT, both handled here:
 *
 *  1. It 500s on a `tools` array — the raw text-completion backends do not
 *     understand the field at all. The contract therefore travels in the
 *     PROMPT only, and `tools` / `tool_choice` / `parallel_tool_calls` are
 *     removed from the outbound body.
 *  2. Its OpenAI-compatible facade rejects a content ARRAY that holds a single
 *     text part (`requiresPlainStringContent` in the registry entry). Every
 *     message is therefore flattened to a plain string before it goes out.
 */

const AIHORDE_BASE_URL = "https://oai.aihorde.net";
const AIHORDE_CHAT_PATH = "/v1/chat/completions";
const AIHORDE_MODELS_PATH = "/v1/models";

/**
 * AI Horde accepts an anonymous placeholder bearer — no account, no key. This
 * is the same value the registry entry declares as `anonymousApiKey`.
 */
const AIHORDE_ANONYMOUS_KEY = "0000000000";

const JSON_HEADERS: Record<string, string> = { "Content-Type": "application/json" };
const SSE_HEADERS: Record<string, string> = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
};

type ChatMessage = { role: string; content: unknown; tool_calls?: unknown };

/** The subset of AI Horde's OpenAI-compatible completion we read. */
type AihordeCompletion = {
  id?: string;
  created?: number;
  usage?: unknown;
  choices?: Array<{ message?: { content?: string } }>;
};

/** Flattens a message's content to the plain string AI Horde's facade accepts. */
function flattenContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (!part || typeof part !== "object") return "";
        const record = part as Record<string, unknown>;
        return typeof record.text === "string" ? record.text : "";
      })
      .join("");
  }
  if (content === null || content === undefined) return "";
  return String(content);
}

function flattenMessages(messages: unknown): ChatMessage[] {
  if (!Array.isArray(messages)) return [];
  const out: ChatMessage[] = [];
  for (const message of messages) {
    if (!message || typeof message !== "object") continue;
    const record = message as Record<string, unknown>;
    out.push({
      role: typeof record.role === "string" ? record.role : "user",
      content: flattenContent(record.content),
    });
  }
  return out;
}

export class AihordeExecutor extends BaseExecutor {
  constructor() {
    super("aihorde", PROVIDERS["aihorde"] ?? { id: "aihorde", baseUrl: AIHORDE_BASE_URL });
  }

  buildUrl(_model: string, _stream: boolean, _urlIndex = 0): string {
    return AIHORDE_BASE_URL + AIHORDE_CHAT_PATH;
  }

  buildHeaders(): Record<string, string> {
    return {
      ...JSON_HEADERS,
      Authorization: `Bearer ${AIHORDE_ANONYMOUS_KEY}`,
    };
  }

  override async execute(input: ExecuteInput): Promise<ExecutorExecuteResult> {
    const url = AIHORDE_BASE_URL + AIHORDE_CHAT_PATH;
    const headers = this.buildHeaders();
    const body = (input.body ?? {}) as Record<string, unknown>;

    // The shared prompt-emulated tool contract: injects the <tool> protocol
    // into the messages so the model learns the client tools, and hands back
    // the requested tool schemas for the response side.
    const { hasTools, requestedTools, effectiveMessages } = prepareToolMessages(
      body,
      flattenMessages(body.messages)
    );

    // Scope this nudge to AI Horde: do not alter the contract used by other
    // executors or relax nonce/name validation to accept narrated examples.
    if (hasTools) {
      effectiveMessages.push({
        role: "system",
        content:
          "When the user's task needs an available client tool, your complete reply must be " +
          "one <tool>JSON</tool> block using the name, arguments and exact _nonce from the " +
          "client-tool contract above. Emit the block itself, not instructions or an example. " +
          "Do not include planning, thinking text, markdown fences, simulated results or a " +
          "claim that the tool is unavailable. The client will execute the tool and return " +
          "its result in a later turn. If no tool is needed, answer normally.",
      });
    }

    // AI Horde 500s on a tools[] array, so the contract travels in the prompt
    // only. `stream: false` upstream keeps the reply in one buffer, which is
    // what the marker parser needs.
    //
    // The model id needs care. chatCore normally sets body.model to the bare
    // id, but the body can arrive WITHOUT one, and AI Horde answers
    // "Model None not known!" to a missing model. So the id is taken from
    // input.model (the executor's target) when the body has none, and only
    // the PROVIDER prefix is stripped -- model ids legitimately contain "/"
    // ("aphrodite/TheDrummer/Cydonia-24B-v4.3"), so path segments must not
    // be touched (the same rule the default executor follows).
    const bodyModel =
      typeof body.model === "string" && body.model.trim().length > 0
        ? body.model.trim()
        : String(input.model ?? "").trim();
    let modelId = bodyModel;
    for (const prefix of ["aihorde/", "horde/"]) {
      if (modelId.startsWith(prefix)) {
        modelId = modelId.slice(prefix.length);
        break;
      }
    }

    const chatBody: Record<string, unknown> = {
      ...body,
      model: modelId,
      messages: flattenMessages(effectiveMessages),
      stream: false,
    };
    delete chatBody.tools;
    delete chatBody.tool_choice;
    delete chatBody.parallel_tool_calls;

    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(chatBody),
        signal: input.signal ?? undefined,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        response: errorResponse(502, `AI Horde request failed: ${message}`),
        url,
        headers,
        transformedBody: chatBody,
      };
    }

    const raw = await response.text();
    if (!response.ok) {
      return {
        response: errorResponse(
          response.status,
          `AI Horde ${response.status}: ${raw.slice(0, 400)}`
        ),
        url,
        headers,
        transformedBody: chatBody,
      };
    }

    let parsed: AihordeCompletion | null = null;
    try {
      parsed = JSON.parse(raw) as AihordeCompletion;
    } catch {
      return {
        response: errorResponse(502, "AI Horde returned a non-JSON body"),
        url,
        headers,
        transformedBody: chatBody,
      };
    }

    const upstreamContent: string = parsed?.choices?.[0]?.message?.content ?? "";
    const { content, toolCalls, finishReason } = hasTools
      ? buildToolAwareResult(upstreamContent, requestedTools, "aihorde", true)
      : { content: upstreamContent, toolCalls: null, finishReason: "stop" };

    const message: Record<string, unknown> = { role: "assistant", content };
    if (toolCalls && toolCalls.length > 0) message.tool_calls = toolCalls;

    const completion = {
      id: typeof parsed?.id === "string" ? parsed.id : `aihorde-${Date.now()}`,
      object: "chat.completion",
      created: typeof parsed?.created === "number" ? parsed.created : Math.floor(Date.now() / 1000),
      model: input.model,
      choices: [{ index: 0, message, finish_reason: finishReason }],
      ...(parsed?.usage ? { usage: parsed.usage } : {}),
    };

    if (input.stream) {
      // A streaming client gets the single upstream completion replayed as SSE.
      const chunks: string[] = [];
      const base = {
        id: completion.id,
        object: "chat.completion.chunk",
        created: completion.created,
        model: completion.model,
      };
      chunks.push(
        `data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] })}\n\n`
      );
      chunks.push(
        `data: ${JSON.stringify({
          ...base,
          choices: [
            {
              index: 0,
              delta: toolCalls && toolCalls.length > 0 ? { tool_calls: toolCalls } : { content },
              finish_reason: null,
            },
          ],
        })}\n\n`
      );
      chunks.push(
        `data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: {}, finish_reason: finishReason }] })}\n\n`
      );
      chunks.push("data: [DONE]\n\n");
      const sse = new ReadableStream<Uint8Array>({
        start(controller) {
          const encoder = new TextEncoder();
          for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
          controller.close();
        },
      });
      return {
        response: new Response(sse, { status: 200, headers: SSE_HEADERS }),
        url,
        headers,
        transformedBody: chatBody,
      };
    }

    return {
      response: new Response(JSON.stringify(completion), { status: 200, headers: JSON_HEADERS }),
      url,
      headers,
      transformedBody: chatBody,
    };
  }
}

export { AIHORDE_BASE_URL, AIHORDE_MODELS_PATH };
export default AihordeExecutor;
