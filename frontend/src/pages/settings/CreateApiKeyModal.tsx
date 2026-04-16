import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Check, AlertTriangle, X } from "lucide-react";
import {
  createApiKey,
  type ApiKeyCreated,
  type ApiKeyScope,
  ALL_API_KEY_SCOPES,
} from "../../api/apiKeys";

interface Props {
  onClose: () => void;
}

type ExpiryChoice = "never" | "30" | "90" | "365";

const EXPIRY_LABELS: Record<ExpiryChoice, string> = {
  never: "Never expires",
  "30": "30 days",
  "90": "90 days",
  "365": "1 year",
};

function expiryToDays(v: ExpiryChoice): number | null {
  return v === "never" ? null : parseInt(v, 10);
}

/**
 * Two-stage modal: (1) configure name/scopes/expiry, (2) reveal the secret
 * exactly once. The only way to leave stage 2 is the explicit
 * "I've saved this" button -- we refuse to close on overlay click or ESC so
 * the user cannot accidentally lose the only copy of their token.
 */
export function CreateApiKeyModal({ onClose }: Props) {
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>([...ALL_API_KEY_SCOPES]);
  const [expiry, setExpiry] = useState<ExpiryChoice>("never");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () =>
      createApiKey({
        name: name.trim(),
        scopes,
        expires_in_days: expiryToDays(expiry),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setCreated(data);
      setError(null);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to create API key.");
    },
  });

  function toggleScope(s: ApiKeyScope) {
    setScopes((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    );
  }

  async function copySecret() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy to clipboard. Select and copy manually.");
    }
  }

  const canSubmit =
    name.trim().length > 0 && scopes.length > 0 && !createMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface border border-border rounded-xl p-6 w-full max-w-lg mx-4 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-fg text-lg font-medium">
            {created ? "Your new API key" : "Create API key"}
          </h3>
          {/* Close X is only allowed BEFORE reveal. After reveal, the user must
              confirm via "I've saved this" -- see note below. */}
          {!created && (
            <button
              onClick={onClose}
              className="text-muted hover:text-fg transition p-1"
              title="Cancel"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {!created ? (
          <div className="flex flex-col gap-4">
            <div>
              <label className="text-xs text-muted block mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. macbook"
                className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
                autoFocus
              />
              <p className="text-muted text-xs mt-1">
                Allowed: letters, digits, <code>_</code>, <code>-</code>.
              </p>
            </div>

            <div>
              <label className="text-xs text-muted block mb-1">Scopes</label>
              <div className="flex flex-col gap-1">
                {ALL_API_KEY_SCOPES.map((s) => (
                  <label
                    key={s}
                    className="flex items-center gap-2 text-sm text-fg font-mono"
                  >
                    <input
                      type="checkbox"
                      checked={scopes.includes(s)}
                      onChange={() => toggleScope(s)}
                      className="accent-accent"
                    />
                    {s}
                  </label>
                ))}
              </div>
              <p className="text-muted text-xs mt-1">
                API keys only work on SSH-key endpoints today. A scope here is
                required to call the matching SSH-key operation.
              </p>
            </div>

            <div>
              <label className="text-xs text-muted block mb-1">Expiry</label>
              <select
                value={expiry}
                onChange={(e) => setExpiry(e.target.value as ExpiryChoice)}
                className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              >
                {(Object.keys(EXPIRY_LABELS) as ExpiryChoice[]).map((k) => (
                  <option key={k} value={k}>
                    {EXPIRY_LABELS[k]}
                  </option>
                ))}
              </select>
            </div>

            {error && <p className="text-failed text-sm">{error}</p>}

            <div className="flex justify-end gap-2 mt-2">
              <button
                onClick={onClose}
                className="border border-border text-muted hover:text-fg rounded-md px-4 py-2 text-sm transition"
              >
                Cancel
              </button>
              <button
                onClick={() => createMut.mutate()}
                disabled={!canSubmit}
                className="bg-accent text-bg font-medium rounded-md px-4 py-2 text-sm hover:brightness-110 transition disabled:opacity-50"
              >
                {createMut.isPending ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-2 text-failed text-sm bg-failed/10 border border-failed/40 rounded-md p-3">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>
                Copy this token now — you will not be able to see it again.
                The server only keeps a one-way hash.
              </span>
            </div>
            <div>
              <label className="text-xs text-muted block mb-1">Token</label>
              <div className="flex gap-2">
                <code
                  className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-xs font-mono break-all select-all"
                  title="Click to select"
                >
                  {created.secret}
                </code>
                <button
                  onClick={copySecret}
                  className="shrink-0 border border-border text-muted hover:text-accent rounded-md px-3 transition"
                  title="Copy to clipboard"
                >
                  {copied ? <Check size={16} className="text-passed" /> : <Copy size={16} />}
                </button>
              </div>
            </div>
            <div className="text-xs text-muted">
              <div>
                <span className="text-muted">Prefix:</span>{" "}
                <code className="text-fg font-mono">{created.prefix}</code>
              </div>
              <div>
                <span className="text-muted">Scopes:</span>{" "}
                <code className="text-fg font-mono">
                  {created.scopes.join(", ")}
                </code>
              </div>
              <div>
                <span className="text-muted">Expires:</span>{" "}
                <span className="text-fg">
                  {created.expires_at
                    ? new Date(created.expires_at).toLocaleString()
                    : "never"}
                </span>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="bg-accent text-bg font-medium rounded-md px-4 py-2 text-sm hover:brightness-110 transition"
              >
                I've saved this
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
