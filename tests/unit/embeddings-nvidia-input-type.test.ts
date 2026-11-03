import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.DATA_DIR = mkdtempSync(join(tmpdir(), "omniroute-embeddings-nvidia-"));

const { handleEmbedding } = await import("../../open-sse/handlers/embeddings.ts");
const { v1EmbeddingsSchema, MAX_EMBEDDING_INLINE_ITEM_BYTES } = await import("../../src/shared/validation/schemas/apiV1.ts");

// Issue #1378: NVIDIA NIM asymmetric embedding models (e.g. nvidia/nv-embedqa-e5-v5)
// require an `input_type` parameter ("query" | "passage"); without it the upstream
// returns 400 "'input_type' parameter is required". OmniRoute must inject the
// registered model-level default when the client omits input_type, and must respect
// a client-supplied input_type when present.

function captureFetch(captured: { body?: Record<string, unknown>; url?: string }) {
  return async (url: unknown, options: { headers?: unknown; body?: unknown } = {}) => {
    captured.url = String(url);
    captured.body = JSON.parse(String(options.body || "{}"));
    return new Response(
      JSON.stringify({
        data: [{ object: "embedding", embedding: [0.1, 0.2], index: 0 }],
        usage: { prompt_tokens: 4, total_tokens: 4 },
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };
}

test("Nemotron 3.5 embedding models route to NVIDIA with query default and passage override", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown>; url?: string } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;
  try {
    for (const model of ["nvidia/nemotron-3.5-embed-1b", "nvidia/nemotron-3.5-embed-8b"]) {
    for (const inputType of [undefined, "passage"]) {
      const result = await handleEmbedding({
        body: {
          model: `nvidia/${model}`,
          input: "synthetic example",
          ...(inputType ? { input_type: inputType } : {}),
        },
        credentials: { apiKey: "nvidia-key" },
        log: null,
      });
      assert.equal(result.success, true);
      assert.equal(captured.url, "https://integrate.api.nvidia.com/v1/embeddings");
      assert.equal(captured.body?.model, model);
      assert.equal(captured.body?.input_type, inputType ?? "query");
    }
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("NVIDIA image passages are preserved and image queries are rejected", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown>; url?: string } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;
  const image = "data:image/png;base64," + "A".repeat(24000);
  try {
    const body = { model: "nvidia/nvidia/nemotron-3.5-embed-1b", input: [image], modality: ["image"] };
    const rejected = await handleEmbedding({ body, credentials: { apiKey: "test" }, log: null });
    assert.equal(rejected.success, false);
    assert.equal(rejected.status, 400);
    assert.equal(captured.body, undefined);
    const result = await handleEmbedding({ body: { ...body, input_type: "passage" }, credentials: { apiKey: "test" }, log: null });
    assert.equal(result.success, true);
    assert.deepEqual(captured.body?.input, [image]);
    assert.deepEqual(captured.body?.modality, ["image"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("NVIDIA image input passes the public schema and rejects oversized data before dispatch", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown>; url?: string } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;
  try {
    const image = "data:image/png;base64," + "A".repeat(24000);
    const body = { model: "nvidia/nvidia/nemotron-3.5-embed-8b", input: ["example", image], modality: ["text", "image"], input_type: "passage" };
    assert.equal(v1EmbeddingsSchema.safeParse(body).success, true);
    const result = await handleEmbedding({ body, credentials: { apiKey: "test" }, log: null });
    assert.equal(result.success, true);
    assert.deepEqual(captured.body?.input, ["example", image]);
    assert.deepEqual(captured.body?.modality, ["text", "image"]);
    captured.body = undefined;
    const oversized = "data:image/png;base64," + "A".repeat(Math.ceil(MAX_EMBEDDING_INLINE_ITEM_BYTES / 3) * 4 + 100);
    const refused = await handleEmbedding({ body: { ...body, input: [oversized] }, credentials: { apiKey: "test" }, log: null });
    assert.equal(refused.success, false);
    assert.equal(refused.status, 400);
    assert.equal(captured.body, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("NVIDIA rejects malformed image data and retains the text length guard", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown>; url?: string } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;
  try {
    const body = { model: "nvidia/nvidia/nemotron-3.5-embed-8b", input_type: "passage", input: ["data:image/png;base64,@@@"] };
    const refused = await handleEmbedding({ body, credentials: { apiKey: "test" }, log: null });
    assert.equal(refused.status, 400);
    assert.equal(captured.body, undefined);
    const result = await handleEmbedding({ body: { ...body, input: ["x".repeat(24000)] }, credentials: { apiKey: "test" }, log: null });
    assert.equal(result.success, true);
    assert.equal((captured.body?.input as string[])[0].length, 20000);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("handleEmbedding injects NVIDIA asymmetric default input_type when client omits it", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown> } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;

  try {
    const result = await handleEmbedding({
      body: {
        model: "nvidia/nvidia/nv-embedqa-e5-v5",
        input: "What is the capital of France?",
      },
      credentials: { apiKey: "nvidia-key" },
      log: null,
    });

    assert.equal(result.success, true);
    // The model-level default input_type must be forwarded to the upstream body.
    assert.equal(
      captured.body?.input_type,
      "query",
      "expected NVIDIA asymmetric model default input_type to be injected"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("handleEmbedding respects a client-supplied input_type (does not overwrite)", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown> } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;

  try {
    const result = await handleEmbedding({
      body: {
        model: "nvidia/nvidia/nv-embedqa-e5-v5",
        input: "Paris is the capital of France.",
        input_type: "passage",
      },
      credentials: { apiKey: "nvidia-key" },
      log: null,
    });

    assert.equal(result.success, true);
    assert.equal(
      captured.body?.input_type,
      "passage",
      "expected client-supplied input_type to be respected, not overwritten by the default"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("handleEmbedding does not inject input_type for symmetric models without a default", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { body?: Record<string, unknown> } = {};
  globalThis.fetch = captureFetch(captured) as typeof fetch;

  try {
    const result = await handleEmbedding({
      body: {
        model: "openai/text-embedding-3-small",
        input: "hello world",
      },
      credentials: { apiKey: "openai-key" },
      log: null,
    });

    assert.equal(result.success, true);
    assert.equal(
      "input_type" in (captured.body || {}),
      false,
      "symmetric models without a default must not receive an injected input_type"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
