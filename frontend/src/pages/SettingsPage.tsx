import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Key, Plug, Plus, Pencil, Zap, Check, AlertCircle, RefreshCw, X } from "lucide-react";
import { listSshKeys, uploadSshKey, replaceSshKey, deleteSshKey } from "../api/keys";
import type { SshKeyInfo } from "../api/keys";
import {
  listConnections,
  deleteConnection,
  testConnection,
  type Connection,
  type ConnectionTestResult,
  type ConnectionTestCredentials,
} from "../api/connections";
import { ConnectionForm } from "../components/ConnectionForm";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const certRef = useRef<HTMLInputElement>(null);

  const [keyName, setKeyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  // When set, the upload form is in "replace existing key" mode for this
  // key name. The key file becomes required, the name field is hidden, and
  // the submit button calls the PUT endpoint instead of POST.
  const [replaceTarget, setReplaceTarget] = useState<string | null>(null);

  // Connection form state.
  const [editing, setEditing] = useState<Connection | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});

  // Interactive gateway test: which connection is requesting credentials.
  const [testCredsFor, setTestCredsFor] = useState<string | null>(null);
  const [testPassword, setTestPassword] = useState("");
  const [testOtp, setTestOtp] = useState("");

  const { data: keys, isLoading: keysLoading } = useQuery<SshKeyInfo[]>({
    queryKey: ["ssh-keys"],
    queryFn: listSshKeys,
  });

  const { data: connections, isLoading: connectionsLoading } = useQuery<Connection[]>({
    queryKey: ["connections"],
    queryFn: listConnections,
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
      // Connections reference keys by name, so no Connection records change
      // — but the key list shows fingerprints, which we want to refresh.
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

  const deleteConnMut = useMutation({
    mutationFn: deleteConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });

  const testConnMut = useMutation({
    mutationFn: ({
      name,
      credentials,
    }: {
      name: string;
      credentials?: ConnectionTestCredentials;
    }) => testConnection(name, credentials),
    onSuccess: (data, { name }) => {
      setTestResults((prev) => ({ ...prev, [name]: data }));
      setTestCredsFor(null);
      setTestPassword("");
      setTestOtp("");
    },
    onError: (e: unknown, { name }) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setTestResults((prev) => ({
        ...prev,
        [name]: {
          ok: false,
          error: typeof detail === "string" ? detail : "Test failed.",
        },
      }));
      setTestCredsFor(null);
      setTestPassword("");
      setTestOtp("");
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
    // Scroll the form into view so the user sees what they're editing.
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
    <div className="p-6 max-w-3xl mx-auto flex flex-col gap-6">
      <h1 className="text-fg text-2xl font-semibold">Settings</h1>

      {/* SSH Keys section */}
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

        {/* Upload / replace form. The same widgets cover both cases —
            in replace mode the name input is hidden and the submit button
            wires to PUT instead of POST. */}
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
              // No `accept` filter on purpose: keys downloaded from CSCS arrive
              // as `cscs-key` (no extension), which any extension-based filter
              // greys out in the OS file picker. Users know what they're picking.
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

        {/* Keys table */}
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

      {/* Connections section */}
      <div className="bg-surface border border-border rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-fg text-lg font-medium flex items-center gap-2">
            <Plug size={18} />
            Connections
          </h2>
          {!showNewForm && !editing && (
            <button
              onClick={() => setShowNewForm(true)}
              className="flex items-center gap-1.5 text-sm text-accent hover:brightness-110 transition border border-accent/50 rounded-md px-3 py-1.5"
            >
              <Plus size={14} />
              Add connection
            </button>
          )}
        </div>
        <p className="text-muted text-sm mb-5">
          Each connection describes a remote target (host, user, optional
          ProxyJump, environment activation). When you start a run, you pick
          one of your connections — or "Local" — independently of the
          architecture.
        </p>

        {(showNewForm || editing) && (
          <div className="mb-5">
            <ConnectionForm
              initial={editing ?? undefined}
              onCancel={() => {
                setShowNewForm(false);
                setEditing(null);
              }}
              onSaved={() => {
                setShowNewForm(false);
                setEditing(null);
              }}
            />
          </div>
        )}

        {connectionsLoading ? (
          <p className="text-muted text-sm">Loading connections...</p>
        ) : connections && connections.length > 0 ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted text-left">
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Target</th>
                <th className="pb-2 font-medium">Gateway</th>
                <th className="pb-2 font-medium">Env</th>
                <th className="pb-2 font-medium w-32"></th>
              </tr>
            </thead>
            <tbody>
              {connections.map((c) => {
                const result = testResults[c.name];
                const isInteractiveGateway =
                  c.gateway != null && c.gateway.auth_method === "interactive";
                return (
                  <tr
                    key={c.name}
                    className="border-b border-border last:border-0"
                  >
                    <td className="py-2.5 text-fg font-mono">
                      {c.name}
                      {result && (
                        <span className="ml-2 inline-flex items-center align-middle">
                          {result.ok ? (
                            <Check size={14} className="text-passed" />
                          ) : (
                            <AlertCircle size={14} className="text-failed" />
                          )}
                        </span>
                      )}
                      {result?.ok && result.whoami && (
                        <span className="ml-1 text-passed text-xs">
                          ({result.whoami})
                        </span>
                      )}
                      {result && !result.ok && result.error && (
                        <div className="text-failed text-xs font-sans">
                          {result.error}
                        </div>
                      )}

                      {/* Inline credential form for testing interactive gateways */}
                      {testCredsFor === c.name && (
                        <div className="mt-2 p-3 bg-bg border border-border rounded-md flex flex-col gap-2 font-sans">
                          <p className="text-xs text-muted">
                            Enter gateway credentials for{" "}
                            <span className="text-fg">{c.gateway?.host}</span>{" "}
                            to test the connection. Used once and discarded.
                          </p>
                          <div className="flex gap-2">
                            <input
                              type="password"
                              placeholder="Gateway password"
                              value={testPassword}
                              onChange={(e) => setTestPassword(e.target.value)}
                              className="flex-1 bg-bg border border-border rounded-md px-2 py-1.5 text-fg text-xs focus:outline-none focus:border-accent"
                              autoComplete="off"
                            />
                            <input
                              type="text"
                              inputMode="numeric"
                              placeholder="OTP code"
                              value={testOtp}
                              onChange={(e) => setTestOtp(e.target.value)}
                              className="w-24 bg-bg border border-border rounded-md px-2 py-1.5 text-fg text-xs focus:outline-none focus:border-accent"
                              autoComplete="off"
                            />
                            <button
                              onClick={() => {
                                testConnMut.mutate({
                                  name: c.name,
                                  credentials: {
                                    gateway_password: testPassword,
                                    gateway_otp: testOtp,
                                  },
                                });
                              }}
                              disabled={
                                testConnMut.isPending ||
                                !testPassword ||
                                !testOtp
                              }
                              className="bg-accent text-bg text-xs font-medium rounded-md px-3 py-1.5 hover:brightness-110 transition disabled:opacity-50"
                            >
                              {testConnMut.isPending ? "Testing..." : "Test"}
                            </button>
                            <button
                              onClick={() => {
                                setTestCredsFor(null);
                                setTestPassword("");
                                setTestOtp("");
                              }}
                              className="text-muted hover:text-fg transition p-1"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 text-muted font-mono text-xs">
                      {c.user}@{c.host}
                      {c.port !== 22 ? `:${c.port}` : ""}
                    </td>
                    <td className="py-2.5 text-muted font-mono text-xs">
                      {c.gateway
                        ? `${c.gateway.user}@${c.gateway.host}${
                            isInteractiveGateway ? " (2FA)" : ""
                          }`
                        : "\u2014"}
                    </td>
                    <td className="py-2.5 text-muted text-xs">{c.env.style}</td>
                    <td className="py-2.5">
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => {
                            if (isInteractiveGateway) {
                              setTestCredsFor(c.name);
                              setTestPassword("");
                              setTestOtp("");
                            } else {
                              testConnMut.mutate({ name: c.name });
                            }
                          }}
                          disabled={testConnMut.isPending}
                          className="text-muted hover:text-accent transition p-1"
                          title="Test connection"
                        >
                          <Zap size={15} />
                        </button>
                        <button
                          onClick={() => {
                            setEditing(c);
                            setShowNewForm(false);
                          }}
                          className="text-muted hover:text-fg transition p-1"
                          title="Edit"
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          onClick={() => deleteConnMut.mutate(c.name)}
                          disabled={deleteConnMut.isPending}
                          className="text-muted hover:text-failed transition p-1"
                          title="Delete"
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
          !showNewForm && (
            <p className="text-muted text-sm">
              No connections yet. Click <span className="text-fg">Add connection</span> to
              create one.
            </p>
          )
        )}
      </div>
    </div>
  );
}
