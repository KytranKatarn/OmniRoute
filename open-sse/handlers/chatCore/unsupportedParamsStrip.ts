// open-sse/handlers/chatCore/unsupportedParamsStrip.ts
// Extracted from handleChatCore (chatCore god-file decomposition) so the
// unsupported-params strip + tool-history flattening can be unit tested
// directly instead of only through the full handleChatCore pipeline.
//
// Live incident: AI Horde (registry unsupportedParams: ["tools", ...]) 500'd
// on real combo traffic even after `tools`/`tool_choice` were correctly
// stripped from the live request, because the conversation HISTORY still
// carried a prior turn's role:"assistant" tool_calls and role:"tool" result
// messages (left over from before the combo failed over from a tool-capable
// model). AI Horde's raw completion backend doesn't understand those message
// shapes at all, regardless of whether live `tools` is present. flattenToolHistory
// already existed, fully unit-tested, for exactly this — it just had zero call
// sites anywhere in the request pipeline.
import { flattenToolHistory } from "../../utils/flattenToolHistory.ts";

export interface UnsupportedParamsStripResult {
  strippedParams: string[];
}

/**
 * Deletes each unsupported param present on `body` (mutates in place, matching
 * the original inline behavior). When "tools" is unsupported for this model —
 * regardless of whether THIS particular request happens to carry a live
 * `tools` array — also flattens any tool_calls/tool-result messages in
 * `body.messages` into plain assistant prose. A model that can't do tool
 * calling can't do it whether or not the current request includes `tools`;
 * gating on "was tools actually present this time" missed the common case of
 * stale tool-call history left over from before a combo failover, with no
 * live `tools` param on the request that inherited it.
 */
export function stripUnsupportedParams(
  body: Record<string, unknown>,
  unsupported: readonly string[],
  emulatedToolCalling: boolean = false
): UnsupportedParamsStripResult {
  const strippedParams: string[] = [];
  for (const param of unsupported) {
    // Emulated-tool providers (e.g. AI Horde, #7424) handle `tools` in their
    // executor even though the raw backend rejects the field, so keep `tools`
    // on the body for the executor to consume (it strips it before sending).
    // Every other unsupported param is still stripped.
    if (param === "tools" && emulatedToolCalling) continue;
    if (Object.hasOwn(body, param)) {
      strippedParams.push(param);
      delete body[param];
    }
  }

  // History flattening must still run for emulated providers: their raw
  // backends reject role:"tool"/tool_calls message shapes regardless of
  // whether this request carries a live `tools` param.
  if (unsupported.includes("tools") && Array.isArray(body.messages)) {
    body.messages = flattenToolHistory(body.messages as Record<string, unknown>[]);
  }

  return { strippedParams };
}
