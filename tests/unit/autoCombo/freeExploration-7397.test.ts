/**
 * #7397: the FREE tier must explore its pool MORE, not less.
 *
 * The free pool's members are new upstreams with no quality history, and the
 * quality signal is what decides the top tier. That is a cold-start trap: the
 * one model that has been serving accumulates quality, wins the top tier, and
 * therefore keeps serving — while every other model stays cold and can never
 * overtake it.
 *
 * Measured on the live DS9: the free combo's pool was 21 candidates (20
 * browser-backed models plus one relay) and ONE of them answered effectively
 * every request. At the default 5% exploration each of the other 20 got well
 * under one call a day — nowhere near enough to accumulate any signal.
 *
 * Exploration is the mechanism that breaks the loop: it samples the pool
 * uniformly, so cold candidates get tried, accumulate quality, and become
 * competitive.
 *
 * These tests assert the RATE, and — more importantly — that it is scoped:
 * a non-free combo must keep the default rate, and the env var must be able
 * to turn the free tier's rate off.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { createVirtualAutoComboFromPrepared } from "../../../open-sse/services/autoCombo/virtualFactory";

type Spec = Parameters<typeof createVirtualAutoComboFromPrepared>[2];

const emptyPrepared = { regularCandidates: [], familyCandidates: [] } as never;

async function explorationRateFor(spec: Spec | undefined): Promise<number> {
  const combo = await createVirtualAutoComboFromPrepared(emptyPrepared, undefined, spec);
  return (combo.autoConfig as { explorationRate: number }).explorationRate;
}

describe("#7397: the free tier explores more than the default", () => {
  const original = process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE;

  beforeEach(() => {
    delete process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE;
  });

  afterEach(() => {
    if (original === undefined) delete process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE;
    else process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE = original;
  });

  it("gives a free-tier combo a higher exploration rate than the default", async () => {
    const free = await explorationRateFor({ category: "coding", tier: "free" });
    const defaultRate = await explorationRateFor(undefined);

    expect(defaultRate).toBe(0.05);
    expect(free).toBeGreaterThan(defaultRate);
  });

  it("covers the flat free overlay too (auto/best-free has tier=free, no category)", async () => {
    const free = await explorationRateFor({ tier: "free" });
    expect(free).toBeGreaterThan(0.05);
  });

  it("leaves every non-free tier on the default rate", async () => {
    expect(await explorationRateFor({ category: "coding", tier: "pro" })).toBe(0.05);
    expect(await explorationRateFor({ category: "coding" })).toBe(0.05);
    expect(await explorationRateFor({ category: "reasoning" })).toBe(0.05);
  });

  it("lets the env var turn the free tier's rate off", async () => {
    process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE = "0";
    expect(await explorationRateFor({ category: "coding", tier: "free" })).toBe(0);
  });

  it("honours an explicit env var value", async () => {
    process.env.OMNIROUTE_AUTO_FREE_EXPLORATION_RATE = "0.4";
    expect(await explorationRateFor({ category: "coding", tier: "free" })).toBe(0.4);
  });
});
