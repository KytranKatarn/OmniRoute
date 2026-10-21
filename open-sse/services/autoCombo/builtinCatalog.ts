import type { ModelCapabilityResolutionSnapshot } from "@/lib/modelCapabilities";

import type { AutoVariant } from "./autoPrefix";
import { VALID_VARIANTS } from "./autoPrefix";
import type { AutoComboSpec, PreparedVirtualAutoComboInputs } from "./virtualFactory";
import { parseAutoSuffix, type AutoCategory, type AutoTier } from "./suffixComposition";
import { isValidModelFamily, AUTO_FAMILY_IDS, type ModelFamily } from "./modelFamily";

export { AUTO_FAMILY_IDS };

/**
 * Built-in `auto/*` catalog → AutoVariant resolution.
 *
 * The dashboard advertises a zero-setup `auto/*` catalog (e.g. `auto/best-coding`).
 * Each catalog id maps to a router variant and is materialized into a virtual
 * auto-combo on demand via `createVirtualAutoCombo`, without requiring persisted DB
 * combo rows. Extracted from `chatHelpers.ts` so that handler stays under the
 * file-size cap and the catalog lives alongside the rest of the autoCombo service.
 */

export const VALID_AUTO_VARIANTS = new Set<AutoVariant>(VALID_VARIANTS);

export const AUTO_TEMPLATE_VARIANTS: Record<string, AutoVariant | undefined> = {
  "auto/best-coding": "coding",
  "auto/best-reasoning": "smart",
  "auto/best-fast": "fast",
  "auto/best-vision": "smart",
  "auto/best-chat": undefined,
  "auto/best-coding-fast": "fast",
  "auto/pro-coding": "coding",
  "auto/pro-reasoning": "smart",
  "auto/pro-vision": "smart",
  "auto/pro-chat": undefined,
  "auto/pro-fast": "fast",
  "auto/coding": "coding",
  "auto/fast": "fast",
  "auto/chat": undefined,
  // #4235 Phase A: these are valid variants (parseAutoPrefix accepts them) and
  // the README advertises them, but they were missing from this catalog so
  // `/v1/models` + the dashboard never listed them. Surface them explicitly.
  "auto/cheap": "cheap",
  "auto/offline": "offline",
  "auto/smart": "smart",
  // auto/claude-{opus,sonnet,haiku} are model-FAMILY ids (#15675), resolved by
  // `isValidModelFamily` — not weight-pack variants (those left the pool unfiltered).
  "auto/best-free": "cheap",
  // Subscription-first routing (see `subscriptionLadder.ts`). `auto/subscription`
  // maps to no weight variant on purpose: its pool is already restricted to
  // plan-included connections, so the scorer should rank them on merit rather
  // than bias toward cheap/fast within an allowance the operator already paid for.
  "auto/subscription": undefined,
  "auto/thrifty": "cheap",
  // Chaos mode — parallel dispatch to top-N stable models
  "auto/best-chaos": "chaos",
  "auto/chaos": "chaos",
};

/**
 * #4235 Phase B — curated `auto/<category>[:<tier>]` combos advertised in `/v1/models`
 * and the dashboard. ANY valid `auto/<category>:<tier>` resolves on demand (so clients
 * can ask for combinations not listed here); this curated set keeps the advertised
 * catalog from exploding into the full category × tier matrix.
 */
export const AUTO_SUFFIX_VARIANTS: string[] = [
  "auto/coding:fast",
  "auto/coding:cheap",
  "auto/coding:free",
  "auto/coding:pro",
  "auto/coding:reliable",
  "auto/reasoning",
  "auto/reasoning:pro",
  "auto/vision",
  "auto/multimodal",
];

/**
 * Flat `auto/*` ids that carry a tier overlay even though they are not written
 * in `<category>:<tier>` form. `auto/best-free` established the pattern; the
 * two subscription-first ids reuse it so a caller can ask for the behavior
 * without also having to pick a category.
 */
export const FLAT_TIER_OVERLAY_IDS: Record<string, AutoTier> = {
  "auto/best-free": "free",
  "auto/subscription": "subscription",
  "auto/thrifty": "thrifty",
};

type ResolvedAutoVariant =
  { recognized: true; variant: AutoVariant | undefined } | { recognized: false };

export function resolveAutoVariant(modelStr: string, suffix: string): ResolvedAutoVariant {
  if (Object.prototype.hasOwnProperty.call(AUTO_TEMPLATE_VARIANTS, modelStr)) {
    return { recognized: true, variant: AUTO_TEMPLATE_VARIANTS[modelStr] };
  }
  if (VALID_AUTO_VARIANTS.has(suffix as AutoVariant)) {
    return { recognized: true, variant: suffix as AutoVariant };
  }
  return { recognized: false };
}

/**
 * Recognize any built-in `auto/*` id: a flat-variant template (legacy) OR a
 * `auto/<category>[:<tier>]` suffix (#4235 Phase B). Used by the chat handler to
 * decide whether an `auto/` model is a valid built-in before materializing it.
 */
export function isRecognizedBuiltinAuto(modelStr: string, suffix: string): boolean {
  return (
    resolveAutoVariant(modelStr, suffix).recognized ||
    parseAutoSuffix(suffix).valid ||
    isValidModelFamily(suffix)
  );
}

/**
 * #6328 (follow-up to #6495 / #6512): recognize built-in `auto/*` ids whose
 * intent is paid-tier only, so callers can REMOVE — not just hide — them from
 * advertised catalogs when the operator opts into `hidePaidModels`.
 *
 * Two shapes qualify as paid-tier:
 *   - flat variants prefixed `auto/pro-*` (e.g. `auto/pro-coding`)
 *   - suffix variants with the `:pro` tier (e.g. `auto/coding:pro`)
 *
 * Non-`pro` `auto/*` ids (auto/coding, auto/best-*, auto/coding:free, …) keep
 * their advertised status; the candidate-pool filter in `virtualFactory` (#6512)
 * already excludes paid backends from them at request time. `auto/<family>` ids
 * are unaffected — the family is a backend selector, not a tier.
 */
export function isPaidTierAutoId(autoId: string): boolean {
  if (typeof autoId !== "string" || !autoId.startsWith("auto/")) return false;
  const suffix = autoId.slice("auto/".length);
  if (suffix.startsWith("pro-")) return true;
  const parsed = parseAutoSuffix(suffix);
  return parsed.valid && parsed.tier === "pro";
}

/**
 * Resolved spec for a built-in `auto/*` id: either a flat variant (legacy) or
 * a category/tier overlay (#4235 Phase B). Category `vision`/`multimodal` adds
 * a candidate filter so the virtual combo only scores vision-capable models.
 */
export type BuiltinAutoSpec =
  | { variant: AutoVariant | undefined }
  | { category: AutoCategory; tier?: AutoTier }
  | { family: ModelFamily };

/**
 * Vision-flavored flat ids that MUST resolve to the `vision` category (candidate
 * filter by capability), not to a flat variant: the vision-bridge guardrail and
 * its self-loop depend on `auto/best-vision` picking a model that can actually
 * see images. Mapping it to `smart` scored ALL candidates and resolved to
 * text-only models (e.g. deepseek-v4-flash-free), breaking every describe call.
 */
const VISION_CATEGORY_AUTO_IDS: Record<string, { category: "vision"; tier?: AutoTier }> = {
  "auto/best-vision": { category: "vision" },
  "auto/pro-vision": { category: "vision", tier: "pro" },
};

/**
 * Pure resolver for a built-in `auto/*` id. Extracted from
 * `createBuiltinAutoCombo` so the catalog mapping is unit-testable without
 * materializing a virtual combo (which requires the DB).
 */
export function resolveBuiltinAutoSpec(modelStr: string, suffix: string): BuiltinAutoSpec {
  const visionSpec = VISION_CATEGORY_AUTO_IDS[modelStr];
  if (visionSpec) return visionSpec;

  const resolved = resolveAutoVariant(modelStr, suffix);
  if (resolved.recognized) {
    return { variant: resolved.variant };
  }

  if (isValidModelFamily(suffix)) return { family: suffix };

  const parsed = parseAutoSuffix(suffix);
  if (parsed.valid) {
    return {
      category: parsed.category as AutoCategory,
      ...(parsed.tier ? { tier: parsed.tier } : {}),
    };
  }

  return { variant: undefined };
}

/**
 * Catalog-side check: true iff `modelStr` is exactly `auto/<suffix>` for a
 * non-empty suffix that `createBuiltinAutoCombo(modelStr, suffix)` materializes
 * instead of throwing "Unknown built-in auto combo".
 *
 * The exact-suffix guard lives HERE only. The request path
 * (`chatHelpers.ts` → `createBuiltinAutoCombo(modelStr, suffix)` with the raw
 * model and the parsed suffix) keeps the historical, more lenient
 * `isRecognizedBuiltinAuto(modelStr, suffix)` contract unchanged.
 */
export function isResolvableBuiltinAutoId(modelStr: string): boolean {
  if (typeof modelStr !== "string" || !modelStr.startsWith("auto/")) return false;
  const suffix = modelStr.slice("auto/".length);
  if (!suffix) return false;
  return isRecognizedBuiltinAuto(modelStr, suffix);
}

/** The `(variant, spec)` pair `createBuiltinAutoCombo` hands to the virtual factory. */
export type BuiltinAutoMaterialization = {
  variant: AutoVariant | undefined;
  spec: AutoComboSpec | undefined;
};

/**
 * Pure: the `(variant, spec)` arguments `createBuiltinAutoCombo` materializes a
 * built-in `auto/*` id with, or `null` when it is not a recognized built-in
 * (the caller throws "Unknown built-in auto combo").
 *
 * Collapses the historical four-branch chain (category → defined variant →
 * template-without-variant → category parse → family) into one decision while
 * keeping its exact outputs, including the category-before-family precedence
 * for a suffix that would parse both ways. Equivalence is pinned by
 * tests/unit/autoCombo/builtin-materialize-equivalence.test.ts.
 */
export function resolveBuiltinAutoMaterialization(
  modelStr: string,
  suffix: string
): BuiltinAutoMaterialization | null {
  if (!isRecognizedBuiltinAuto(modelStr, suffix)) return null;
  const spec = resolveBuiltinAutoSpec(modelStr, suffix);
  if ("variant" in spec) {
    const overlayTier = FLAT_TIER_OVERLAY_IDS[modelStr];
    return {
      variant: spec.variant,
      spec: overlayTier ? { tier: overlayTier } : spec.variant !== undefined ? {} : undefined,
    };
  }
  if ("category" in spec) {
    return {
      variant: undefined,
      spec: { category: spec.category, ...(spec.tier ? { tier: spec.tier } : {}) },
    };
  }
  const parsed = parseAutoSuffix(suffix);
  if (parsed.valid) {
    return { variant: undefined, spec: { category: parsed.category, tier: parsed.tier } };
  }
  return { variant: undefined, spec: { family: spec.family } };
}

/**
 * `includeResolvedCapabilities` defaults to true (the /v1/models catalog caller).
 * The request path (chatHelpers.ts) passes false unless the operator opts in:
 * resolved capabilities feed the snapshot weights, so they change scoring.
 */
export async function prepareBuiltinAutoComboInputs(
  resolutionSnapshot?: ModelCapabilityResolutionSnapshot,
  options: { includeResolvedCapabilities?: boolean } = {}
): Promise<PreparedVirtualAutoComboInputs> {
  const { prepareVirtualAutoComboInputs } = await import("./virtualFactory.ts");
  return prepareVirtualAutoComboInputs({
    includeResolvedCapabilities: options.includeResolvedCapabilities ?? true,
    resolutionSnapshot,
  });
}

/** Prepared inputs, or a loader that is only called when a combo is materialized. */
export type BuiltinAutoComboPreparedSource =
  PreparedVirtualAutoComboInputs | (() => Promise<PreparedVirtualAutoComboInputs>);

/**
 * What each built-in combo is PRACTICAL FOR.
 *
 * Advertised on /v1/models as the entry's `description`. Claude Code's gateway
 * model discovery renders that field in its model picker - an entry without one
 * reads "From gateway" - and other OpenAI-compatible clients surface it the
 * same way. A combo list that only says "auto/coding" tells a caller nothing
 * about whether to pick auto/coding, auto/coding:free or auto/coding:reliable.
 * These one-liners are what make the list a menu rather than a guessing game.
 *
 * Each line answers two questions: what is this good for, and what does it cost
 * you (speed, money, or a narrower pool). Keep them to one sentence.
 */
export const BUILTIN_AUTO_COMBO_DESCRIPTIONS: Record<string, string> = {
  // ── the category presets: pick one when you know the job ──────────────────
  "auto/coding":
    "Routes to whichever connected model is best at code - generation, refactoring, review and debugging. The default pick for anything that writes or changes code.",
  "auto/chat":
    "General conversation and everyday assistant work. No coding or reasoning bias - the balanced default when the task is just a question.",
  "auto/reasoning":
    "For work that needs to think: multi-step problems, maths, analysis, planning. Prefers models that show their reasoning, at some cost in speed.",
  "auto/vision":
    "For anything with an image in it - reading a screenshot, a diagram, a photo. Only routes to models that actually accept images.",
  "auto/multimodal":
    "For mixed image-and-text work where both the picture and the words carry meaning. Needs a model that handles both at once.",

  // ── the tier overlays: same job, a different trade-off ────────────────────
  "auto/coding:fast":
    "Coding at the lowest latency: quick completions, autocomplete, small edits. Pick this when you want the answer now rather than the best answer.",
  "auto/coding:cheap":
    "Coding with cost and quota headroom protected - prefers free and included-in-plan capacity, at some cost in answer quality.",
  "auto/coding:free":
    "Coding on free-tier capacity only. Never spends a paid credit, so it may be slower or less capable - the right pick for a free-only lane.",
  "auto/coding:pro":
    "Coding on premium capacity only, for the work that must be right. Fails closed rather than quietly dropping to a free model.",
  "auto/coding:reliable":
    "Coding weighted toward whichever model has been most dependable lately rather than the one that scores highest. For work that must not fail.",
  "auto/best-free": "The best model available on free capacity right now, whatever the job.",
  "auto/thrifty":
    "Spends as little as it can: the cheapest capable model that can do the job, with free and included-in-plan capacity preferred.",
  "auto/subscription":
    "Only uses capacity your plan already includes, and only where there is quota headroom left. Fails rather than billing you.",

  // ── the weight variants ──────────────────────────────────────────────────
  "auto/fast": "The fastest capable model, whatever the job. For latency-sensitive work.",
  "auto/cheap": "The cheapest capable model, whatever the job. For cost-sensitive work.",
  "auto/smart":
    "The best available model, weighted for quality over speed. The default when you are not sure.",
  "auto/offline": "For when the network is not an option: prefers models that can run locally.",
  "auto/chaos":
    "Fans the same request out to several top models at once and returns every answer. Useful for comparing options, not for normal work.",
  "auto/best-chaos": "The same parallel fan-out, restricted to the most stable models.",

  // ── the 'best' aliases ───────────────────────────────────────────────────
  "auto/best-coding": "The best coding model available right now.",
  "auto/best-coding-fast": "The best coding model available right now, weighted for speed.",
  "auto/best-chat": "The best general assistant model available right now.",
  "auto/best-reasoning": "The best reasoning model available right now.",
  "auto/best-fast": "The fastest model available right now.",
  "auto/best-vision": "The best image-capable model available right now.",

  // ── the premium tier ─────────────────────────────────────────────────────
  "auto/pro-coding": "Coding on premium capacity only.",
  "auto/pro-reasoning": "Reasoning on premium capacity only.",
  "auto/reasoning:pro":
    "Reasoning on premium capacity only. The hardest problems, solved on paid capacity.",
  "auto/pro-vision": "Vision on premium capacity only.",
  "auto/pro-chat": "General chat on premium capacity only.",
  "auto/pro-fast": "Fast work on premium capacity only.",

  // ── the family ids: pin a family, let the router choose within it ─────────
  "auto/gpt":
    "Any model in the GPT family. Use when you want GPT specifically, without pinning the exact version.",
  "auto/claude-opus":
    "Any model in the Claude Opus family - the strongest Claude models, for the hardest work.",
  "auto/claude-sonnet":
    "Any model in the Claude Sonnet family - the balanced Claude models, good at code and writing.",
  "auto/gemini": "Any model in the Gemini family, for very long context and multimodal work.",
  "auto/llama": "Any model in the Llama family, including ones you can run locally.",
  "auto/qwen":
    "Any model in the Qwen family: strong at code and reasoning, and several are small enough to run locally.",
  "auto/glm": "Any model in the GLM family.",
  "auto/kimi": "Any model in the Kimi family: long-context and code-focused.",
  "auto/gemma": "Any model in the Gemma family: small, open, easy to run locally.",
  "auto/mimo": "Any model in the MiMo family.",
  "auto/deepseek":
    "Any model in the DeepSeek family: strong reasoning and code, often at a low price.",
};

export async function createBuiltinAutoCombo(
  modelStr: string,
  suffix: string,
  prepared?: BuiltinAutoComboPreparedSource
) {
  const materialization = resolveBuiltinAutoMaterialization(modelStr, suffix);
  if (!materialization) {
    throw new Error(`Unknown built-in auto combo: ${modelStr}`);
  }
  const { createVirtualAutoCombo, createVirtualAutoComboFromPrepared } =
    await import("./virtualFactory.ts");
  const { variant, spec } = materialization;
  // #16419: `prepared` may be a lazy loader shared across the auto request path.
  const inputs = !prepared
    ? undefined
    : typeof prepared === "function"
      ? await prepared()
      : prepared;
  const virtualCombo = inputs
    ? await createVirtualAutoComboFromPrepared(inputs, variant, spec)
    : await createVirtualAutoCombo(variant, spec);
  virtualCombo.name = modelStr;
  virtualCombo.id = modelStr;
  // #13670: the catalog advertises a combo's own description, and a client
  // that renders a model picker shows it. Without one the entry reads "From
  // gateway", so the list tells a caller nothing about which combo to pick.
  // Set it here so the materialised combo carries it into /v1/models.
  const description = BUILTIN_AUTO_COMBO_DESCRIPTIONS[modelStr];
  if (description) virtualCombo.description = description;
  return virtualCombo;
}
