import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plug,
  Plus,
  Pencil,
  Zap,
  Check,
  AlertCircle,
  Trash2,
  X,
} from "lucide-react";
import {
  listConnections,
  deleteConnection,
  testConnection,
  type Connection,
  type ConnectionTestResult,
  type ConnectionTestCredentials,
} from "../../api/connections";
import { ConnectionForm } from "../../components/ConnectionForm";

/**
 * Per-user named SSH connections. Supports ProxyJump gateways (key-based and
 * interactive 2FA) and an inline "Test" button that opens the chain and runs
 * `whoami` as a smoke test.
 */
export function ConnectionsSection() {
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState<Connection | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});

  const [testCredsFor, setTestCredsFor] = useState<string | null>(null);
  const [testPassword, setTestPassword] = useState("");
  const [testOtp, setTestOtp] = useState("");

  const { data: connections, isLoading: connectionsLoading } = useQuery<Connection[]>({
    queryKey: ["connections"],
    queryFn: listConnections,
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

  return (
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
  );
}
