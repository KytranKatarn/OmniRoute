/**
 * #7397: the auto-combo top tier must be a BAND, not an exact tie.
 *
 * Before this change the top tier meant "within SCORE_EPSILON (1e-4) of the
 * best score". A single model that out-scored the rest — even by a hair —
 * became the ONLY member of the top tier, and the rotator's round-robin then
 * had nothing to spread across. One model answered effectively every request,
 * which defeats the point of a pool: if that model, or the provider behind it,
 * degrades, there is no warm alternative to fall back to.
 *
 * The fix widens the top tier to a fraction of the pool's score RANGE, so
 * genuinely comparable models are treated as tied and the existing round-robin
 * spreads across them.
 *
 * The tests here pin down BOTH halves of the contract:
 *   1. close-scoring models rotate;
 *   2. a CLEARLY better model still wins outright — the band is relative to
 *      the range, so a wide gap stays a wide gap.
 *
 * Each test computes the pool's ACTUAL scores with scorePool() and asserts the
 * geometry it needs (pool range >= the clear-winner threshold, and the two
 * candidates within 5% of that range). That makes the test self-verifying: if
 * a future scoring change moves the geometry, the test says so instead of
 * quietly passing for the wrong reason.
 */

import { describe, it, expect, beforeAll, beforeEach, vi } from "vitest";
import { selectProvider, type AutoComboConfig } from "../../../open-sse/services/autoCombo/engine";
import {
  DEFAULT_WEIGHTS,
  scorePool,
  type ProviderCandidate,
  type ScoringWeights,
} from "../../../open-sse/services/autoCombo/scoring";
import { getTaskFitness } from "../../../open-sse/services/autoCombo/taskFitness";
import { resetDiversity } from "../../../open-sse/services/autoCombo/providerDiversity";

// Stub DB calls introduced by PR #3660 (Arena ELO / models.dev intelligence
// scoring) — this file tests rotation logic, not intelligence scoring.
vi.mock("../../../src/lib/db/modelIntelligence.ts", () => ({
  getModelIntelligenceBySource: vi.fn(() => null),
  setUserFitnessOverrideEntry: vi.fn(),
  deleteUserFitnessOverrideEntry: vi.fn(),
}));

/** Mirrors CLEAR_WINNER_THRESHOLD in engine.ts. */
const CLEAR_WINNER_THRESHOLD = 0.1;
/** Mirrors the default TOP_TIER_BAND in engine.ts. */
const TOP_TIER_BAND = 0.05;

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
    errorRate: 0.01,
    ...overrides,
  };
}

function makeConfig(name: string): AutoComboConfig {
  return {
    id: `test-${name}`,
    name,
    type: "auto",
    candidatePool: [],
    weights: { ...DEFAULT_WEIGHTS },
    explorationRate: 0,
    routerStrategy: "rules",
  };
}

/** The geometry the rotator will see for this pool. */
function geometry(pool: ProviderCandidate[], weights: ScoringWeights) {
  const scored = scorePool(pool, "coding", weights, getTaskFitness);
  const best = scored[0].score;
  const worst = scored[scored.length - 1].score;
  return { scored, best, worst, range: best - worst };
}

// The first getTaskFitness() call in a worker pays the lazy, synchronous
// model-intelligence DB init. Pay it here so the per-test timeout measures
// the test and not first-call setup under parallel load.
beforeAll(() => {
  getTaskFitness("warmup-model", "coding");
}, 30_000);

describe("#7397: the auto-combo top tier is a band, not an exact tie", () => {
  beforeEach(() => {
    resetDiversity();
  });

  it("rotates between two models whose scores are close", () => {
    // quota is the biggest lever that is uniform across the other factors.
    // A/B are within 1% of each other; C is far enough away to stay out of
    // the top band, and it is what makes the pool RANGE exceed the
    // clear-winner threshold so the top-tier-only path is the one exercised.
    const a = makeCandidate({ provider: "prov-a", model: "model-a", quotaRemaining: 100 });
    const b = makeCandidate({ provider: "prov-b", model: "model-b", quotaRemaining: 99 });
    const c = makeCandidate({ provider: "prov-c", model: "model-c", quotaRemaining: 0 });
    const pool = [a, b, c];
    const config = makeConfig("smart");

    const { best, worst, range, scored } = geometry(pool, config.weights);
    const deltaAB = Math.abs(
      (scored.find((s) => s.model === "model-a")?.score ?? 0) -
        (scored.find((s) => s.model === "model-b")?.score ?? 0)
    );

    // The geometry this test depends on — assert it, so a scoring change
    // cannot make this test pass for the wrong reason.
    expect(range).toBeGreaterThanOrEqual(CLEAR_WINNER_THRESHOLD);
    expect(deltaAB).toBeLessThanOrEqual(range * TOP_TIER_BAND);
    expect(deltaAB).toBeGreaterThan(1e-4); // NOT an exact tie under the old rule
    expect(best - worst).toBeGreaterThanOrEqual(CLEAR_WINNER_THRESHOLD);

    const seen = new Set<string>();
    for (let i = 0; i < 60; i++) {
      const result = selectProvider(config, pool, "coding");
      seen.add(`${result.provider}/${result.model}`);
    }

    expect(seen.size).toBeGreaterThanOrEqual(2);
    expect(seen.has("prov-a/model-a")).toBe(true);
  });

  it("still lets a CLEARLY better model win outright", () => {
    // A wide gap must not be narrowed into a tie — that would let a much
    // worse model answer production traffic.
    const best = makeCandidate({
      provider: "prov-best",
      model: "model-best",
      quotaRemaining: 100,
    });
    const muchWorse = makeCandidate({
      provider: "prov-worse",
      model: "model-worse",
      quotaRemaining: 0,
    });
    const pool = [best, muchWorse];
    const config = makeConfig("smart");

    const { range } = geometry(pool, config.weights);
    expect(range).toBeGreaterThanOrEqual(CLEAR_WINNER_THRESHOLD);

    const counts: Record<string, number> = {};
    for (let i = 0; i < 60; i++) {
      const result = selectProvider(config, pool, "coding");
      const key = `${result.provider}/${result.model}`;
      counts[key] = (counts[key] ?? 0) + 1;
    }

    expect(counts["prov-worse/model-worse"] ?? 0).toBe(0);
  });

  it("keeps a single-candidate pool deterministic", () => {
    const only = makeCandidate({ provider: "only", model: "only-model" });
    const config = makeConfig("smart");
    for (let i = 0; i < 10; i++) {
      const result = selectProvider(config, [only], "coding");
      expect(result.provider).toBe("only");
      expect(result.model).toBe("only-model");
    }
  });
});
