/**
 * Live AI Horde chat-model catalog sync (#7379).
 *
 * AI Horde's OpenAI-compatible facade at oai.aihorde.net exposes ~30 chat
 * models via GET /v1/models. The gateway's registry entry only carries 3
 * static fallbacks, so any model not in that list can reach the upstream as
 * "Model None not known!" when the gateway cannot resolve the id.
 *
 * This module fetches the live chat catalog and persists it to
 * `syncedAvailableModels` under the aihorde connection ID so it is available for
 * combo-routing wildcard expansion (`aihorde/*`) and model inference for
 * unprefixed ids, even when the live fetch is temporarily unreachable.
 *
 * Persisted models are non-authoritative (no active connection backs them),
 * so they never gate on `model_not_in_catalog` — they only ADD to what the
 * static registry already offers.
 */

import { persistCanonicalSyncedAvailableModels } from "@/lib/db/models/syncedAvailableModelPersistence";
import { normalizeSyncedAvailableModels } from "@/lib/db/models/synced";
import { safeOutboundFetch } from "@/shared/network/safeOutboundFetch";
import { SAFE_OUTBOUND_FETCH_PRESETS } from "@/shared/network/safeOutboundFetch";
import { getProviderOutboundGuard } from "@/shared/network/outboundUrlGuardPolicy";
import { getRawProviderConnections } from "@/lib/db/providers";

export const AI_HORDE_CHAT_MODELS_URL = "https://oai.aihorde.net/v1/models";
export const AI_HORDE_CHAT_CATALOG_FETCH_TIMEOUT_MS = 15_000;

export interface AihordeChatCatalogModel {
  id: string;
  name: string;
  backend: string;
  quant: string;
  size: number;
  workerThreads: number;
  knownToHorde: boolean;
}

export interface AihordeChatCatalogSnapshot {
  models: AihordeChatCatalogModel[];
  updatedAt: number | null;
  lastError: string | null;
}

type AihordeModelsResponse = {
  object?: string;
  data?: Array<Record<string, unknown>>;
};

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asInt(value: unknown): number | null {
  const parsed = asNumber(value);
  return parsed === null ? null : Math.trunc(parsed);
}

/**
 * Parse the AI Horde /v1/models response into chat catalog entries.
 * Only models with at least one worker thread are included — a model with
 * zero workers cannot serve traffic and should not be advertised.
 */
export function parseAihordeChatModels(payload: unknown): AihordeChatCatalogModel[] {
  const response = payload as AihordeModelsResponse | null;
  const data = response?.data;
  if (!Array.isArray(data)) {
    throw new Error("AI Horde chat catalog must have a data array");
  }

  const models: AihordeChatCatalogModel[] = [];
  for (const item of data) {
    if (!item || typeof item !== "object") continue;

    const id = typeof item.id === "string" ? item.id.trim() : "";
    if (!id) continue;

    const workerThreads = asInt(item.worker_threads ?? 0) ?? 0;
    if (workerThreads <= 0) continue;

    models.push({
      id,
      name: typeof item.name === "string" && item.name.trim().length > 0 ? item.name.trim() : id,
      backend: typeof item.backend === "string" ? item.backend : "unknown",
      quant: typeof item.quant === "string" ? item.quant : "unknown",
      size: asNumber(item.size ?? 0) ?? 0,
      workerThreads,
      knownToHorde: Boolean(item.known_to_horde),
    });
  }

  models.sort((a, b) => a.id.localeCompare(b.id, undefined, { sensitivity: "base" }));
  return models;
}

/**
 * Get the active aihorde connection ID.
 */
async function getAihordeConnectionId(): Promise<string | null> {
  try {
    const connections = await getRawProviderConnections(
      { provider: "aihorde", isActive: true },
      undefined,
      undefined,
      ["id"]
    );
    if (connections.length > 0) {
      return connections[0].id;
    }
  } catch {
    // ignore
  }
  return null;
}

/**
 * Fetch the live AI Horde chat catalog and persist it to syncedAvailableModels.
 * Returns the number of models persisted. On failure returns 0 and records the error.
 */
export async function syncAihordeChatCatalog(): Promise<{
  modelCount: number;
  error: string | null;
}> {
  try {
    const connId = await getAihordeConnectionId();
    if (!connId) {
      return { modelCount: 0, error: "No active aihorde connection found" };
    }

    const response = await safeOutboundFetch(AI_HORDE_CHAT_MODELS_URL, {
      ...SAFE_OUTBOUND_FETCH_PRESETS.modelsDiscovery,
      guard: getProviderOutboundGuard(),
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      return {
        modelCount: 0,
        error: `HTTP ${response.status}`,
      };
    }

    const payload = (await response.json()) as unknown;
    const models = parseAihordeChatModels(payload);

    const normalized = models.map((m) => ({
      id: m.id,
      name: m.name,
      source: "imported",
      supportedEndpoints: ["chat"],
      catalogOrigin: "aihorde-live-sync",
    }));

    persistCanonicalSyncedAvailableModels(`aihorde:${connId}`, normalized, (raw) =>
      normalizeSyncedAvailableModels(raw, "aihorde")
    );

    return { modelCount: models.length, error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { modelCount: 0, error: message };
  }
}

/**
 * One-shot sync for use in tests, boot, or manual triggers.
 */
export async function syncAihordeChatCatalogOnce(): Promise<{
  modelCount: number;
  error: string | null;
}> {
  return syncAihordeChatCatalog();
}

export { AI_HORDE_CHAT_MODELS_URL as default };
