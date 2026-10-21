/**
 * #7397: LKGP must choose the MODEL on merit, not on pool order.
 *
 * The LKGP ("last known good provider") strategy prefers the provider that
 * last worked — that is its whole point and it is preserved. But within that
 * provider it used to take `candidates[0]`, which is a REGISTRY-ORDER choice
 * wearing the costume of a routing decision: the provider registry lists the
 * flagship models first, so the first candidate was always the same model.
 *
 * Measured on the live DS9: the free tier's cloudflare-playground provider
 * resolved to zai-org/glm-5.2 on every request while the other nineteen
 * models in its pool were never tried — and because the choice bypassed
 * scoring, no weight and no exploration rate could ever change it.
 *
 * These tests pin the fix:
 *   1. the best-SCORED model of the last-known-good provider wins;
 *   2. exploration actually reaches the model choice, so a runner-up is tried;
 *   3. stickiness to the PROVIDER is untouched.
 */

import { describe, it, expect } from "vitest";
import {
  selectWithStrategyAsync,
  type RoutingContext,
} from "../../../open-sse/services/autoCombo/routerStrategy";
import {
  DEFAULT_WEIGHTS,
  type ProviderCandidate,
} from "../../../open-sse/services/autoCombo/scoring";

function makeCandidate(overrides: Partial<ProviderCandidate>): ProviderCandidate {
  return {
    provider: "unknown",
    model: "unknown-model",
    quotaRemaining: 100,
    quotaTotal: 100,
    circuitBreakerState: "CLOSED",
    costPer1MTokens: 1,
    p95LatencyMs: 1000,
    latencyStdDev: 100,
    errorRate: 0,
    ...overrides,
  } as ProviderCandidate;
}

function makeContext(overrides: Partial<RoutingContext>): RoutingContext {
  return {
    taskType: "coding",
    weights: { ...DEFAULT_WEIGHTS },
    explorationRate: 0,
    lastKnownGoodProvider: "cfp",
    ...overrides,
  } as RoutingContext;
}

describe("#7397: LKGP picks the model on merit, not on pool order", () => {
  it("does not simply take the first candidate of the last-known-good provider", async () => {
    // The first candidate in pool order is deliberately the WORSE model.
    const worseFirst = makeCandidate({
      provider: "cfp",
      model: "registry-first-but-worse",
      quotaRemaining: 10,
    });
    const better = makeCandidate({
      provider: "cfp",
      model: "actually-better",
      quotaRemaining: 100,
    });
    const other = makeCandidate({
      provider: "other-provider",
      model: "other",
      quotaRemaining: 100,
    });

    const decision = await selectWithStrategyAsync(
      [worseFirst, better, other],
      makeContext({}),
      "lkgp"
    );

    expect(decision.provider).toBe("cfp");
    expect(decision.model).toBe("actually-better");
  });

  it("keeps the traffic on the last-known-good PROVIDER", async () => {
    const cfp = makeCandidate({ provider: "cfp", model: "a", quotaRemaining: 100 });
    const cfp2 = makeCandidate({ provider: "cfp", model: "b", quotaRemaining: 99 });
    const other = makeCandidate({ provider: "other-provider", model: "x", quotaRemaining: 100 });

    for (let i = 0; i < 25; i++) {
      const decision = await selectWithStrategyAsync(
        [cfp, cfp2, other],
        makeContext({ explorationRate: 0.5 }),
        "lkgp"
      );
      expect(decision.provider).toBe("cfp");
    }
  });

  it("lets exploration reach the model choice within that provider", async () => {
    const a = makeCandidate({ provider: "cfp", model: "model-a", quotaRemaining: 100 });
    const b = makeCandidate({ provider: "cfp", model: "model-b", quotaRemaining: 99 });
    const other = makeCandidate({ provider: "other-provider", model: "x", quotaRemaining: 100 });

    const seen = new Set<string>();
    for (let i = 0; i < 80; i++) {
      const decision = await selectWithStrategyAsync(
        [a, b, other],
        makeContext({ explorationRate: 0.5 }),
        "lkgp"
      );
      seen.add(decision.model);
    }

    expect(seen.size).toBeGreaterThanOrEqual(2);
    expect([...seen].every((m) => m === "model-a" || m === "model-b")).toBe(true);
  });

  it("falls back to the rules strategy when the last-known-good provider is gone", async () => {
    const only = makeCandidate({
      provider: "someone-else",
      model: "only-model",
      quotaRemaining: 100,
    });

    const decision = await selectWithStrategyAsync(
      [only],
      makeContext({ lastKnownGoodProvider: "vanished-provider" }),
      "lkgp"
    );

    expect(decision.provider).toBe("someone-else");
    expect(decision.model).toBe("only-model");
  });
});
