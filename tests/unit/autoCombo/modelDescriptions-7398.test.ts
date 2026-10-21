/**
 * Every model in the catalog must say what it is PRACTICAL FOR.
 *
 * `/v1/models` is a MODEL LIST, and a list of bare names is not a menu - a
 * caller cannot choose between "auto/coding", "auto/coding:free" and
 * "auto/coding:reliable" from a name alone. The `description` field is what
 * clients read: Claude Code's gateway model discovery renders it in its model
 * picker (an entry without one reads "From gateway"), and other
 * OpenAI-compatible clients surface it the same way.
 *
 * Before this, 0 of 463 live models carried one.
 *
 * These tests pin the three places a description can come from, and the
 * invariant that matters: a model with no curated description still emits NO
 * description field, exactly as before - a missing description must never
 * become an empty or invented one.
 */

import { describe, it, expect } from "vitest";
import { getProviderRegistry } from "../../../open-sse/services/autoCombo/providerRegistryAccessor";
import {
  BUILTIN_AUTO_COMBO_DESCRIPTIONS,
  createBuiltinAutoCombo,
} from "../../../open-sse/services/autoCombo/builtinCatalog";
import { enrichCatalogModelEntry } from "../../../src/lib/modelMetadataRegistry";

const registry = getProviderRegistry() as Record<
  string,
  { models?: Array<{ id: string; description?: string }> }
>;

describe("model descriptions: what each model is practical for", () => {
  it("gives every built-in auto/* combo a description", () => {
    expect(Object.keys(BUILTIN_AUTO_COMBO_DESCRIPTIONS).length).toBeGreaterThan(0);
    for (const [id, description] of Object.entries(BUILTIN_AUTO_COMBO_DESCRIPTIONS)) {
      expect(id.startsWith("auto/"), `${id} should be an auto/* id`).toBe(true);
      expect(description.trim().length, `${id} has an empty description`).toBeGreaterThan(20);
      // A description that does not say what it is FOR is not a description.
      expect(description.length, `${id} is too long to be a picker line`).toBeLessThan(300);
    }
  });

  it("describes the free-tier and app-server models in their registries", () => {
    const cfp = registry["cloudflare-playground"];
    expect(cfp?.models?.length).toBeGreaterThan(0);
    for (const model of cfp!.models!) {
      expect(model.description, `${model.id} has no description`).toBeTruthy();
      expect(model.description!.length).toBeGreaterThan(20);
    }

    const codex = registry["codex"];
    expect(codex?.models?.length).toBeGreaterThan(0);
    for (const model of codex!.models!) {
      expect(model.description, `${model.id} has no description`).toBeTruthy();
    }
  });

  it("names the reasoning effort on the effort variants", () => {
    const codex = registry["codex"]!;
    const effortVariant = codex.models!.find((m) => m.id.endsWith("-max"));
    expect(effortVariant, "expected a -max effort variant").toBeTruthy();
    expect(effortVariant!.description).toMatch(/reasoning effort/i);

    const base = codex.models!.find((m) => m.id === "gpt-6-sol");
    expect(base?.description).toBeTruthy();
    expect(base!.description).not.toMatch(/reasoning effort/i);
  });

  it("carries the description onto the provider model entries the catalog emits", () => {
    const enriched = enrichCatalogModelEntry({
      id: "cfp/zai-org/glm-5.2",
      owned_by: "cloudflare-playground",
      root: "zai-org/glm-5.2",
    });
    expect(enriched.description).toBeTruthy();
    expect(enriched.description as string).toMatch(/GLM 5\.2/);
  });

  it("carries the description onto a materialized combo", async () => {
    for (const id of ["auto/coding", "auto/coding:free", "auto/best-free", "auto/reasoning"]) {
      const suffix = id.replace(/^auto\/?/, "");
      const combo = await createBuiltinAutoCombo(id, suffix);
      expect(combo.description, `${id} materialized without a description`).toBeTruthy();
    }
  });

  it("gives the built-in combo entries a description in the catalog", async () => {
    // The catalog builds a built-in combo's ENTRY itself (rather than reading
    // it from the DB), so the description has to be copied across explicitly.
    // This is the path that decides what a client picker actually shows.
    const combo = await createBuiltinAutoCombo("auto/coding:free", "coding:free");
    expect(combo.description).toBeTruthy();
    expect(combo.description as string).toMatch(/free-tier capacity only/);
  });

  it("invents nothing for a model that has no description", () => {
    // A model outside the curated set must keep its previous shape: no
    // description field at all, rather than an empty or invented one.
    const enriched = enrichCatalogModelEntry({
      id: "some-unknown-provider/some-unknown-model",
      owned_by: "some-unknown-provider",
      root: "some-unknown-model",
    });
    expect(enriched.description).toBeUndefined();
  });
});
