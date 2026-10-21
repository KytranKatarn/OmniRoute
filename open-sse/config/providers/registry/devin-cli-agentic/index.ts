import type { RegistryEntry } from "../../shared.ts";
import { DEVIN_MODEL_CATALOG } from "../devin/catalog.ts";

export const devin_cli_agenticProvider: RegistryEntry = {
  id: "devin-cli-agentic",
  description:
    "Devin's agentic models - each one drives a coding agent rather than answering a single prompt. Good for delegated multi-step work; not a drop-in chat replacement.",
  alias: "dva",
  format: "claude",
  executor: "devin-cli-agentic",
  baseUrl: "devin://acp/stdio",
  // Authentication is owned exclusively by the official Devin CLI inside its
  // isolated volume. OmniRoute must not import or persist a host credential.
  authType: "none",
  authHeader: "none",
  defaultContextLength: 200000,
  models: DEVIN_MODEL_CATALOG.map((model) => ({
    ...model,
    toolCalling: true,
    supportsReasoning: false,
    supportsVision: false,
  })),
};
