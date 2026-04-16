import { api } from "./client";

export type ApiKeyScope = "ssh-keys:read" | "ssh-keys:write";

export const ALL_API_KEY_SCOPES: readonly ApiKeyScope[] = [
  "ssh-keys:read",
  "ssh-keys:write",
] as const;

export interface ApiKeyInfo {
  id: string;
  name: string;
  prefix: string;
  scopes: ApiKeyScope[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

/**
 * Returned exactly once, when a key is freshly minted or rotated. The
 * `secret` field carries the full `opalx_...` token string — the server
 * cannot return it again.
 */
export interface ApiKeyCreated extends ApiKeyInfo {
  secret: string;
}

export interface ApiKeyCreateRequest {
  name: string;
  scopes: ApiKeyScope[];
  /** `null` means "never expires". */
  expires_in_days: number | null;
}

export async function listApiKeys(): Promise<ApiKeyInfo[]> {
  const res = await api.get<ApiKeyInfo[]>("/api/settings/api-keys");
  return res.data;
}

export async function createApiKey(
  req: ApiKeyCreateRequest
): Promise<ApiKeyCreated> {
  const res = await api.post<ApiKeyCreated>("/api/settings/api-keys", req);
  return res.data;
}

export async function rotateApiKey(id: string): Promise<ApiKeyCreated> {
  const res = await api.post<ApiKeyCreated>(
    `/api/settings/api-keys/${encodeURIComponent(id)}/rotate`
  );
  return res.data;
}

export async function deleteApiKey(id: string): Promise<void> {
  await api.delete(`/api/settings/api-keys/${encodeURIComponent(id)}`);
}
