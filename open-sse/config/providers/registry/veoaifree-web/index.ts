import type { RegistryEntry } from "../../shared.ts";

export const veoaifree_webProvider: RegistryEntry = {
  id: "veoaifree-web",
  description:
    "Free web-backed video generation. Every request goes out to a browser session, so it is slow and heavily rate-limited.",
  alias: "veo-free",
  format: "openai",
  executor: "veoaifree-web",
  baseUrl: "https://veoaifree.com/wp-admin/admin-ajax.php",
  authType: "none",
  authHeader: "none",
  models: [
    { id: "veo", name: "VEO 3.1", toolCalling: false },
    { id: "seedance", name: "Seedance", toolCalling: false },
  ],
};
