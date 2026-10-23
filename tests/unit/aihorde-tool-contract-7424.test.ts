import { test } from "node:test";
import assert from "node:assert/strict";
import { AihordeExecutor } from "../../open-sse/executors/aihorde.ts";
import { getToolNonce } from "../../open-sse/translator/webTools.ts";
import { NOAUTH_PROVIDERS } from "../../src/shared/constants/providers/noauth.ts";

test("7424: AI Horde keeps its live emulated free-pool opt-in", () => {
  assert.equal(NOAUTH_PROVIDERS.aihorde.toolCalling, "emulated");
});

function tools() {
  return [
    {
      type: "function",
      function: {
        name: "get_weather",
        description: "Get weather for a city",
        parameters: {
          type: "object",
          properties: { city: { type: "string" } },
          required: ["city"],
        },
      },
    },
  ];
}

test("7424: capture actual upstream prompt, resolved model and nonce-bound response", async (t) => {
  const requested = tools();
  let captured: Record<string, unknown>;
  t.mock.method(globalThis, "fetch", async (_url: unknown, init: RequestInit) => {
    captured = JSON.parse(String(init.body));
    const envelope = {
      name: "get_weather",
      arguments: { city: "Toronto" },
      _nonce: getToolNonce(requested),
    };
    return Response.json({
      choices: [{ message: { content: `<tool>${JSON.stringify(envelope)}</tool>` } }],
    });
  });
  const result = await new AihordeExecutor().execute({
    model: "google/gemma-4-31b",
    stream: false,
    credentials: {},
    body: {
      messages: [{ role: "user", content: "What is the weather in Toronto?" }],
      tools: requested,
      max_tokens: 2048,
    },
  });
  assert.equal(captured.model, "google/gemma-4-31b");
  assert.equal(captured.max_tokens, 2048);
  assert.equal(captured.tools, undefined);
  const messages = captured.messages as Array<{ role: string; content: string }>;
  assert.ok(messages.some((m) => m.content.includes(getToolNonce(requested))));
  assert.match(messages.at(-1).content, /complete reply must be one <tool>JSON<\/tool> block/);
  const completion = await result.response.json();
  assert.equal(completion.choices[0].finish_reason, "tool_calls");
  assert.equal(completion.choices[0].message.tool_calls[0].function.name, "get_weather");
});

for (const kind of ["missing-nonce", "wrong-nonce", "unknown-tool", "truncated"]) {
  test(`7424: ${kind} never becomes an executable tool call`, async (t) => {
    const requested = tools();
    t.mock.method(globalThis, "fetch", async () => {
      const envelope: Record<string, unknown> = {
        name: kind === "unknown-tool" ? "not_requested" : "get_weather",
        arguments: { city: "Toronto" },
        _nonce: kind === "wrong-nonce" ? "wrong" : getToolNonce(requested),
      };
      if (kind === "missing-nonce") delete envelope._nonce;
      let content = `<tool>${JSON.stringify(envelope)}</tool>`;
      if (kind === "truncated") content = content.slice(0, -12);
      return Response.json({ choices: [{ message: { content } }] });
    });
    const result = await new AihordeExecutor().execute({
      model: "google/gemma-4-31b",
      stream: false,
      credentials: {},
      body: { messages: [{ role: "user", content: "Weather?" }], tools: requested },
    });
    const completion = await result.response.json();
    assert.equal(completion.choices[0].message.tool_calls, undefined);
    assert.equal(completion.choices[0].finish_reason, "stop");
  });
}

test("7424: streaming clients receive a validated nonce-bound tool call", async (t) => {
  const requested = tools();
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({
      choices: [
        {
          message: {
            content: `<tool>${JSON.stringify({
              name: "get_weather",
              arguments: { city: "Toronto" },
              _nonce: getToolNonce(requested),
            })}</tool>`,
          },
        },
      ],
    })
  );
  const result = await new AihordeExecutor().execute({
    model: "google/gemma-4-31b",
    stream: true,
    credentials: {},
    body: { messages: [{ role: "user", content: "Weather?" }], tools: requested },
  });
  const stream = await result.response.text();
  assert.match(stream, /"tool_calls"/);
  assert.match(stream, /get_weather/);
  assert.match(stream, /data: \[DONE\]/);
});

test("7424: ordinary chats do not acquire tool instructions", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url: unknown, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    assert.deepEqual(body.messages, [{ role: "user", content: "Hello" }]);
    return Response.json({ choices: [{ message: { content: "Hello" } }] });
  });
  const result = await new AihordeExecutor().execute({
    model: "google/gemma-4-31b",
    stream: false,
    credentials: {},
    body: { messages: [{ role: "user", content: "Hello" }] },
  });
  const completion = await result.response.json();
  assert.equal(completion.choices[0].message.content, "Hello");
});
