import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Key, RefreshCw, X } from "lucide-react";
import {
  listSshKeys,
  uploadSshKey,
  replaceSshKey,
  deleteSshKey,
  type SshKeyInfo,
} from "../../api/keys";

/**
 * SSH-key management: upload, in-place replace (for short-lived daily keys),
 * and delete. Deletion is blocked by the backend when any of the user's
 * connections references the key -- the UI surfaces the dependent connection
 * names in the error toast.
 */
export function SshKeysSection() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const certRef = useRef<HTMLInputElement>(null);

  const [keyName, setKeyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<string | null>(null);

  const { data: keys, isLoading: keysLoading } = useQuery<SshKeyInfo[]>({
    queryKey: ["ssh-keys"],
    queryFn: listSshKeys,
  });

  function clearFormInputs() {
    setKeyName("");
    if (fileRef.current) fileRef.current.value = "";
    if (certRef.current) certRef.current.value = "";
  }

  function extractErrorDetail(e: unknown, fallback: string): string {
    return (
      (e as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail ?? fallback
    );
  }

  const uploadMut = useMutation({
    mutationFn: ({ name, file, cert }: { name: string; file: File; cert?: File }) =>
      uploadSshKey(name, file, cert),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["ssh-keys"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      clearFormInputs();
      setError(null);
      setSuccess(`Key "${data.name}" uploaded.`);
    },
    onError: (e: unknown) => {
      setError(extractErrorDetail(e, "Upload failed."));
      setSuccess(null);
    },
  });

  const replaceMut = useMutation({
    mutationFn: ({ name, file, cert }: { name: string; file: File; cert?: File }) =>
      replaceSshKey(name, file, cert),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["ssh-keys"] });
      clearFormInputs();
      setReplaceTarget(null);
      setError(null);
      setSuccess(`Key "${data.name}" replaced.`);
    },
    onError: (e: unknown) => {
      setError(extractErrorDetail(e, "Replace failed."));
      setSuccess(null);
    },
  });

  const deleteKeyMut = useMutation({
    mutationFn: deleteSshKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssh-keys"] });
      setError(null);
      setSuccess(null);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      if (
        detail &&
        typeof detail === "object" &&
        "dependent_connections" in detail
      ) {
        const deps = (detail as { dependent_connections: string[] })
          .dependent_connections;
        setError(
          `Cannot delete key — it's used by connection(s): ${deps.join(", ")}. Unlink them first.`,
        );
      } else if (typeof detail === "string") {
        setError(detail);
      } else {
        setError("Failed to delete key.");
      }
      setSuccess(null);
    },
  });

  function handleUpload() {
    setError(null);
    setSuccess(null);
    const file = fileRef.current?.files?.[0];
    const cert = certRef.current?.files?.[0];
    if (!file) {
      setError("Please select a private key file.");
      return;
    }
    if (replaceTarget) {
      replaceMut.mutate({ name: replaceTarget, file, cert });
      return;
    }
    if (!keyName.trim()) {
      setError("Please enter a key name.");
      return;
    }
    uploadMut.mutate({ name: keyName.trim(), file, cert });
  }

  function startReplace(name: string) {
    setReplaceTarget(name);
    clearFormInputs();
    setError(null);
    setSuccess(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function cancelReplace() {
    setReplaceTarget(null);
    clearFormInputs();
    setError(null);
  }

  const isReplaceMode = replaceTarget !== null;
  const submitPending = uploadMut.isPending || replaceMut.isPending;

  return (
    <div className="bg-surface border border-border rounded-xl p-6">
      <h2 className="text-fg text-lg font-medium mb-4 flex items-center gap-2">
        <Key size={18} />
        SSH Keys
      </h2>
      <p className="text-muted text-sm mb-5">
        Private keys you upload here are stored in your personal user
        directory and are referenced by name from your{" "}
        <span className="text-fg">connections</span> below.
      </p>

      <div className="flex flex-col gap-3 mb-6">
        {isReplaceMode && (
          <div className="flex items-center gap-2 text-sm bg-bg border border-accent/40 rounded-md px-3 py-2">
            <RefreshCw size={14} className="text-accent" />
            <span className="text-muted">
              Replacing key{" "}
              <code className="text-fg font-mono">{replaceTarget}</code> in
              place. Connections referencing this key keep working.
            </span>
          </div>
        )}
        <div className="flex gap-2">
          {!isReplaceMode && (
            <input
              type="text"
              placeholder="Key name (e.g. cscs-key)"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            />
          )}
          <input
            ref={fileRef}
            type="file"
            className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm file:mr-3 file:border-0 file:bg-transparent file:text-accent file:text-sm file:font-medium"
          />
        </div>
        <div className="flex gap-2 items-center">
          <label className="text-xs text-muted whitespace-nowrap">
            Certificate {isReplaceMode ? "(optional, blank = keep existing)" : "(optional)"}:
          </label>
          <input
            ref={certRef}
            type="file"
            className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm file:mr-3 file:border-0 file:bg-transparent file:text-muted file:text-sm file:font-medium"
          />
        </div>
        <p className="text-muted text-xs">
          Upload a certificate file (e.g. <code className="text-fg">cscs-key-cert.pub</code>) if
          your HPC site uses certificate-based SSH authentication (CSCS Alps / Daint).
        </p>
        <div className="flex gap-2">
          <button
            onClick={handleUpload}
            disabled={submitPending}
            className="flex items-center justify-center gap-2 bg-accent text-bg font-medium rounded-md py-2 text-sm hover:brightness-110 transition disabled:opacity-50 w-fit px-5"
          >
            {isReplaceMode ? <RefreshCw size={15} /> : <Upload size={15} />}
            {submitPending
              ? isReplaceMode
                ? "Replacing..."
                : "Uploading..."
              : isReplaceMode
                ? "Replace Key"
                : "Upload Key"}
          </button>
          {isReplaceMode && (
            <button
              onClick={cancelReplace}
              disabled={submitPending}
              className="flex items-center justify-center gap-2 border border-border text-muted hover:text-fg font-medium rounded-md py-2 text-sm transition disabled:opacity-50 w-fit px-4"
            >
              <X size={15} />
              Cancel
            </button>
          )}
        </div>
        {error && <p className="text-failed text-sm">{error}</p>}
        {success && <p className="text-passed text-sm">{success}</p>}
      </div>

      {keysLoading ? (
        <p className="text-muted text-sm">Loading keys...</p>
      ) : keys && keys.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-left">
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 font-medium">Fingerprint</th>
              <th className="pb-2 font-medium">Added</th>
              <th className="pb-2 font-medium w-20"></th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const isReplacingThis = replaceTarget === k.name;
              return (
                <tr
                  key={k.name}
                  className={`border-b border-border last:border-0 ${
                    isReplacingThis ? "bg-bg/40" : ""
                  }`}
                >
                  <td className="py-2.5 text-fg font-mono">{k.name}</td>
                  <td className="py-2.5 text-muted font-mono text-xs truncate max-w-[200px]">
                    {k.fingerprint ?? "-"}
                  </td>
                  <td className="py-2.5 text-muted">
                    {new Date(k.created_at).toLocaleDateString()}
                  </td>
                  <td className="py-2.5">
                    <div className="flex gap-1 justify-end">
                      <button
                        onClick={() => startReplace(k.name)}
                        disabled={submitPending}
                        className={`transition p-1 ${
                          isReplacingThis
                            ? "text-accent"
                            : "text-muted hover:text-accent"
                        }`}
                        title={`Replace ${k.name} (e.g. new daily Daint key)`}
                      >
                        <RefreshCw size={15} />
                      </button>
                      <button
                        onClick={() => deleteKeyMut.mutate(k.name)}
                        disabled={deleteKeyMut.isPending}
                        className="text-muted hover:text-failed transition p-1"
                        title={`Delete ${k.name}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-muted text-sm">
          No SSH keys registered. Upload a private key to enable remote
          execution.
        </p>
      )}
    </div>
  );
}
