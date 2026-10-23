import { test } from "node:test";
import assert from "node:assert/strict";
import { transformToOmniRoute } from "../../src/lib/pricingSync.ts";

test("7425: Anthropic source prices reach both Claude alias and canonical id", () => {
  const result = transformToOmniRoute({
    "anthropic/claude-sonnet-4-20250514": {
      litellm_provider: "anthropic",
      input_cost_per_token: 0.000003,
      output_cost_per_token: 0.000015,
      cache_read_input_token_cost: 0.0000003,
      mode: "chat",
    },
  });
  const expected = { input: 3, output: 15, cached: 0.3, mode: "chat" };
  for (const provider of ["anthropic", "cc", "claude"]) {
    assert.deepEqual(result[provider]?.["claude-sonnet-4-20250514"], expected);
  }
  assert.equal(result.openai, undefined);
  assert.equal(result.cx, undefined);
});

test("7425: OpenAI source prices reach both Codex alias and canonical id", () => {
  const result = transformToOmniRoute({
    "openai/gpt-4o": {
      litellm_provider: "openai",
      input_cost_per_token: 0.0000025,
      output_cost_per_token: 0.00001,
      mode: "chat",
    },
  });
  for (const provider of ["openai", "cx", "codex"]) {
    assert.deepEqual(result[provider]?.["gpt-4o"], { input: 2.5, output: 10, mode: "chat" });
  }
  // A model offered through another transport does not inherit OpenAI's rate.
  assert.equal(result["opencode-zen"], undefined);
  assert.equal(result.aihorde, undefined);
  assert.equal(result.cc, undefined);
});

test("7425: third-party pricing never overwrites OpenAI pricing", () => {
  const result = transformToOmniRoute({
    "openai/gpt-4o": {
      litellm_provider: "openai",
      input_cost_per_token: 0.0000025,
      output_cost_per_token: 0.00001,
    },
    "opencode-zen/gpt-4o": {
      litellm_provider: "opencode-zen",
      input_cost_per_token: 0,
      output_cost_per_token: 0,
    },
  });
  assert.equal(result.openai["gpt-4o"].input, 2.5);
  assert.equal(result.codex["gpt-4o"].input, 2.5);
  assert.equal(result["opencode-zen"]["gpt-4o"].input, 0);
});
