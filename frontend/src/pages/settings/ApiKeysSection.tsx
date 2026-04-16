import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Terminal, Plus, RefreshCw, Trash2, AlertTriangle, Check, Copy } from "lucide-react";
import {
  listApiKeys,
  rotateApiKey,
  deleteApiKey,
  type ApiKeyInfo,
  type ApiKeyCreated,
} from "../../api/apiKeys";
import { CreateApiKeyModal } from "./CreateApiKeyModal";

/**
 * API keys list + create / rotate / revoke actions.
 *
 * Scope today is hardcoded to SSH-key endpoints only -- see
 * `api_keys.ApiKeyScope` on the backend. The row actions invalidate the
 * `api-keys` query cache on success; rotate also opens a reveal overlay so
 * the new secret is shown exactly once.
 */
export function ApiKeysSection() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [rotatedKey, setRotatedKey] = useState<ApiKeyCreated | null>(null);
  const [rotatedCopied, setRotatedCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: keys, isLoading } = useQuery<ApiKeyInfo[]>({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  const rotateMut = useMutation({
    mutationFn: (id: string) => rotateApiKey(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setRotatedKey(data);
      setError(null);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to rotate API key.");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setError(null);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to revoke API key.");
    },
  });

  function onRevoke(id: string, name: string) {
    const ok = window.confirm(
      `Revoke API key "${name}"? Clients using this key will immediately start getting 401s.`,
    );
    if (ok) deleteMut.mutate(id);
  }

  function onRotate(id: string, name: string) {
    const ok = window.confirm(
      `Rotate API key "${name}"? The current secret will stop working immediately. You will get a new one to distribute.`,
    );
    if (ok) rotateMut.mutate(id);
  }

  async function copyRotatedSecret() {
    if (!rotatedKey) return;
    try {
      await navigator.clipboard.writeText(rotatedKey.secret);
      setRotatedCopied(true);
      setTimeout(() => setRotatedCopied(false), 2000);
    } catch {
      setError("Could not copy to clipboard. Select and copy manually.");
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <Terminal size={18} />
          API keys
        </h2>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 text-sm text-accent hover:brightness-110 transition border border-accent/50 rounded-md px-3 py-1.5"
        >
          <Plus size={14} />
          New API key
        </button>
      </div>
      <p className="text-muted text-sm mb-5">
        Long-lived bearer tokens scoped to SSH-key endpoints only. Use them
        to automate key rotation from a laptop (see{" "}
        <code className="text-fg">deploy/opalx-keys.sh</code>). A leaked key
        cannot touch runs, connections, or your account settings.
      </p>

      {error && (
        <div className="mb-4 flex items-start gap-2 text-failed text-sm bg-failed/10 border border-failed/40 rounded-md p-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {isLoading ? (
        <p className="text-muted text-sm">Loading API keys...</p>
      ) : keys && keys.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-left">
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 font-medium">Prefix</th>
              <th className="pb-2 font-medium">Scopes</th>
              <th className="pb-2 font-medium">Created</th>
              <th className="pb-2 font-medium">Last used</th>
              <th className="pb-2 font-medium">Expires</th>
              <th className="pb-2 font-medium w-20"></th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr
                key={k.id}
                className="border-b border-border last:border-0"
              >
                <td className="py-2.5 text-fg font-mono">{k.name}</td>
                <td className="py-2.5 text-muted font-mono text-xs">
                  {k.prefix}
                </td>
                <td className="py-2.5 text-muted font-mono text-xs">
                  {k.scopes.join(", ")}
                </td>
                <td className="py-2.5 text-muted text-xs">
                  {new Date(k.created_at).toLocaleDateString()}
                </td>
                <td className="py-2.5 text-muted text-xs">
                  {k.last_used_at
                    ? new Date(k.last_used_at).toLocaleString()
                    : "never"}
                </td>
                <td className="py-2.5 text-muted text-xs">
                  {k.expires_at
                    ? new Date(k.expires_at).toLocaleDateString()
                    : "never"}
                </td>
                <td className="py-2.5">
                  <div className="flex gap-1 justify-end">
                    <button
                      onClick={() => onRotate(k.id, k.name)}
                      disabled={rotateMut.isPending}
                      className="text-muted hover:text-accent transition p-1"
                      title={`Rotate ${k.name}`}
                    >
                      <RefreshCw size={15} />
                    </button>
                    <button
                      onClick={() => onRevoke(k.id, k.name)}
                      disabled={deleteMut.isPending}
                      className="text-muted hover:text-failed transition p-1"
                      title={`Revoke ${k.name}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted text-sm">
          No API keys yet. Click{" "}
          <span className="text-fg">New API key</span> to mint your first
          one.
        </p>
      )}

      {showCreate && (
        <CreateApiKeyModal onClose={() => setShowCreate(false)} />
      )}

      {rotatedKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl p-6 w-full max-w-lg mx-4 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-fg text-lg font-medium">
                API key "{rotatedKey.name}" rotated
              </h3>
            </div>
            <div className="flex items-start gap-2 text-failed text-sm bg-failed/10 border border-failed/40 rounded-md p-3 mb-4">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>
                Copy the new token now — it will not be shown again. The old
                secret has already stopped working.
              </span>
            </div>
            <div className="flex gap-2 mb-4">
              <code className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-xs font-mono break-all select-all">
                {rotatedKey.secret}
              </code>
              <button
                onClick={copyRotatedSecret}
                className="shrink-0 border border-border text-muted hover:text-accent rounded-md px-3 transition"
                title="Copy to clipboard"
              >
                {rotatedCopied ? (
                  <Check size={16} className="text-passed" />
                ) : (
                  <Copy size={16} />
                )}
              </button>
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => {
                  setRotatedKey(null);
                  setRotatedCopied(false);
                }}
                className="bg-accent text-bg font-medium rounded-md px-4 py-2 text-sm hover:brightness-110 transition"
              >
                I've saved this
              </button>
            </div>
            {/* Intentionally no X in the corner -- users must dismiss via the
                confirmation button so the secret isn't lost to a stray click. */}
          </div>
        </div>
      )}
    </div>
  );
}
