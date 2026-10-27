/**
 * The NAMED-BLOCK tool dialect (task #7424).
 *
 * Measured 2026-10-22 against AI Horde's `google/gemma-4-31b` with the
 * gateway's own prompt contract (`prepareToolMessages`): the model answers the
 * plain-text tool contract by naming the tool in its own tag —
 *
 *     <tool>
 *     <get_weather>
 *     {"location": "Toronto"}
 *     </tool>
 *
 * The canonical shape the parser expects puts the name INSIDE the JSON. Without
 * a normalizer the named form is invisible: `parseToolCallsFromText` returns
 * null and the caller gets prose where a tool call was meant.
 *
 * These pin the normalizer's two properties: it makes the named form parse,
 * and it leaves every other dialect byte-for-byte alone.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  normalizeNamedBlockToolCalls,
  parseToolCallsFromText,
} from "../../open-sse/translator/webTools.ts";

const TOOLS = [
  {
    type: "function",
    function: {
      name: "get_weather",
      description: "Get the weather for a city",
      parameters: {
        type: "object",
        properties: { city: { type: "string" } },
        required: ["city"],
      },
    },
  },
];

test("the named-block dialect parses into a tool call", () => {
  const raw = [
    "<thinking>",
    "I see a tool called get_weather. Let me call it.",
    "</thinking>",
    "",
    "<tool>",
    "<get_weather>",
    '{"location": "Toronto"}',
    "</tool>",
  ].join("\n");

  const { toolCalls } = parseToolCallsFromText(raw, "t", TOOLS);
  assert.ok(toolCalls, "the named-block dialect must produce a tool call");
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].function.name, "get_weather");
  assert.equal(toolCalls[0].type, "function");
  const args = JSON.parse(String(toolCalls[0].function.arguments));
  assert.equal(args.location, "Toronto");
});

test("a CANONICAL block is left byte-for-byte alone", () => {
  const raw = `<tool>{"name":"get_weather","arguments":{"city":"Toronto"}}</tool>`;
  assert.equal(normalizeNamedBlockToolCalls(raw), raw);
  const { toolCalls } = parseToolCallsFromText(raw, "t", TOOLS);
  assert.ok(toolCalls);
  assert.equal(toolCalls[0].function.name, "get_weather");
});

test("prose with no tool block is still no tool call", () => {
  const raw = "I cannot call tools right now.";
  assert.equal(normalizeNamedBlockToolCalls(raw), raw);
  assert.equal(parseToolCallsFromText(raw, "t", TOOLS).toolCalls, null);
});

test("a named block whose body is not JSON is left alone", () => {
  const raw = "<tool>\n<get_weather>\nnot json at all\n</tool>";
  assert.equal(normalizeNamedBlockToolCalls(raw), raw);
});

test("the named-block form survives a response that also has prose", () => {
  const raw = 'Here you go.\n<tool>\n<get_weather>\n{"city":"Toronto"}\n</tool>\nHope that helps.';
  const { content, toolCalls } = parseToolCallsFromText(raw, "t", TOOLS);
  assert.ok(toolCalls);
  assert.equal(toolCalls.length, 1);
  assert.ok(content.includes("Here you go."));
  assert.ok(!content.includes("<tool>"), "the tool block must be stripped from the content");
});

test("the SECOND dialect (tool_name tag + XML-ish args) also parses", () => {
  // Measured 2026-10-22 from the same model: the tool name sits in a
  // <tool_name> tag and the arguments are XML-ish elements, not a JSON object.
  const raw = [
    "<tool>",
    "<tool_name>get_weather</tool_name>",
    "<city>Toronto</city>",
    "</tool>",
  ].join("\n");

  const { toolCalls } = parseToolCallsFromText(raw, "t", TOOLS);
  assert.ok(toolCalls, "the <tool_name> dialect must produce a tool call");
  assert.equal(toolCalls[0].function.name, "get_weather");
  const args = JSON.parse(String(toolCalls[0].function.arguments));
  assert.equal(args.city, "Toronto");
});

test("a numeric XML argument keeps its type", () => {
  const raw = "<tool>\n<tool_name>get_weather</tool_name>\n<days>3</days>\n</tool>";
  const { toolCalls } = parseToolCallsFromText(raw, "t", TOOLS);
  assert.ok(toolCalls);
  const args = JSON.parse(String(toolCalls[0].function.arguments));
  assert.equal(args.days, 3);
  assert.strictEqual(typeof args.days, "number");
});
