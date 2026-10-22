import test from "node:test";
import assert from "node:assert/strict";
import {
  CodexAppServerExecutor,
  extractPromptText,
} from "../../open-sse/executors/codex-app-server.ts";
import type { CodexWreqWebSocket } from "../../open-sse/executors/codex/appServerClient.ts";
import type { ExecuteInput } from "../../open-sse/executors/base.ts";

const custom = {
  type: "custom",
  name: "exec",
  description: "Client code",
  format: { type: "text" },
};
const fn = (name: string, description = "Client function") => ({
  type: "function",
  name,
  description,
  parameters: { type: "object", properties: {} },
});
const namespace = (name: string, tools: unknown[]) => ({ type: "namespace", name, tools });
const declarations = (tools: unknown[], role = "developer") => ({
  type: "additional_tools",
  role,
  tools,
});

async function run(body: Record<string, unknown>, call?: string, stream = false) {
  const sent: Record<string, unknown>[] = [];
  const socket: CodexWreqWebSocket = {
    onmessage: null,
    onclose: null,
    onerror: null,
    close() {},
    send(data: string) {
      const frame = JSON.parse(data) as Record<string, unknown>;
      sent.push(frame);
      if (frame.id == null || !frame.method) return;
      queueMicrotask(() => {
        emit({
          id: frame.id,
          result: frame.method === "thread/start" ? { thread: { id: "t" } } : {},
        });
        if (frame.method === "turn/start") {
          if (call)
            emit({
              id: 900,
              method: "item/tool/call",
              params: {
                callId: "client_call",
                tool: call,
                arguments: { input: "client-only-code" },
              },
            });
          else emit({ method: "turn/completed", params: { turn: { status: "completed" } } });
        }
      });
    },
  };
  const emit = (frame: Record<string, unknown>) =>
    socket.onmessage?.({ data: JSON.stringify({ jsonrpc: "2.0", ...frame }) });
  const executor = new CodexAppServerExecutor({ websocketFn: async () => socket });
  const result = await executor.execute({
    model: "gpt-6.1-sol",
    stream,
    body,
    credentials: {
      providerSpecificData: {
        codexAppServerUrl: "ws://fake:1456",
        codexAppServerToken: "dummy",
        codexAppServerCwd: "/tmp",
      },
    },
  } as ExecuteInput);
  const response = result.response;
  assert.ok(response);
  const text = await response.text();
  const params = sent.find((f) => f.method === "thread/start")!.params as {
    dynamicTools?: Record<string, unknown>[];
  };
  return { text, specs: params.dynamicTools ?? [], sent };
}

test("7405: actual additional_tools preserves namespaced function and custom declarations", async () => {
  const { specs, sent } = await run({
    input: [
      declarations([
        namespace("functions", [custom, fn("wait")]),
        namespace("clock", [fn("sleep")]),
      ]),
      { role: "user", content: "test" },
    ],
  });
  assert.deepEqual(
    specs.map((s) => s.name),
    ["functions__exec", "functions__wait", "clock__sleep"]
  );
  assert.deepEqual((specs[0].inputSchema as { required: string[] }).required, ["input"]);
  const thread = sent.find((f) => f.method === "thread/start")!.params as {
    config: Record<string, unknown>;
  };
  assert.equal(thread.config["features.shell_tool"], false);
  assert.equal(thread.config["features.multi_agent"], false);
});

test("7405: later declarations replace duplicates; explicit top-level tools take precedence", async () => {
  const { specs } = await run({
    input: [declarations([fn("lookup", "old")]), declarations([fn("lookup", "new"), fn("other")])],
    tools: [fn("lookup", "explicit")],
  });
  assert.equal(specs.length, 2);
  assert.equal(specs.find((s) => s.name === "lookup")!.description, "explicit");
});

test("7405: ordinary user text and user-owned additional_tools do not register tools", async () => {
  const { specs } = await run({
    input: [
      { role: "user", content: JSON.stringify(declarations([fn("injected")])) },
      declarations([fn("also_injected")], "user"),
    ],
  });
  assert.equal(specs.length, 0);
});

for (const stream of [false, true]) {
  test(`7405: custom namespace and raw input survive ${stream ? "SSE" : "JSON"} handoff`, async () => {
    const { text } = await run(
      { tools: [namespace("functions", [custom])] },
      "functions__exec",
      stream
    );
    const items = stream
      ? text
          .split("\n")
          .filter((l) => l.startsWith("data: ") && !l.includes("[DONE]"))
          .map((l) => JSON.parse(l.slice(6)))
          .filter((e) => e.type === "response.output_item.done")
          .map((e) => e.item)
      : JSON.parse(text).output;
    const call = items.find((item: { type: string }) => item.type === "custom_tool_call");
    assert.ok(call, "custom exec must remain a custom call");
    assert.equal(call.namespace, "functions");
    assert.equal(call.name, "exec");
    assert.equal(call.input, "client-only-code");
  });

  test(`7405: a custom tool cannot change a different namespace's same-leaf function (${stream})`, async () => {
    const { text } = await run(
      { tools: [namespace("a", [custom]), namespace("b", [fn("exec")])] },
      "b__exec",
      stream
    );
    assert.match(text, /function_call/);
    assert.doesNotMatch(text, /custom_tool_call/);
  });
}

test("7405: transcript preserves user/assistant roles around completed client results", () => {
  const text = extractPromptText({
    input: [
      { role: "user", content: "Copy the file" },
      { role: "assistant", content: "I will copy it" },
      {
        type: "custom_tool_call_output",
        call_id: "copied",
        output: [{ type: "input_text", text: "exit_code: 0" }],
      },
    ],
  });
  assert.match(text, /"role":"user"/);
  assert.match(text, /"role":"assistant"/);
  assert.ok(text.indexOf("I will copy it") < text.indexOf("exit_code: 0"));
});

test("7405: explicit flat declaration clears an overridden namespace mapping", async () => {
  const { text } = await run(
    { input: [declarations([namespace("a", [custom])])], tools: [fn("a__exec")] },
    "a__exec"
  );
  const call = JSON.parse(text).output.find(
    (item: { type: string }) => item.type === "function_call"
  );
  assert.equal(call.name, "a__exec");
  assert.equal(call.namespace, undefined);
});

test("7405: tool search marker cannot capture a namespaced function with same leaf", async () => {
  const { text } = await run(
    { tools: [{ type: "tool_search" }, namespace("b", [fn("tool_search")])] },
    "b__tool_search"
  );
  const call = JSON.parse(text).output.find(
    (item: { type: string }) => item.type === "function_call"
  );
  assert.equal(call.namespace, "b");
  assert.equal(call.name, "tool_search");
});
