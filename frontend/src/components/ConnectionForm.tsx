import { useState } from "react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { Save, X } from "lucide-react";
import { listSshKeys } from "../api/keys";
import type { SshKeyInfo } from "../api/keys";
import {
  createConnection,
  updateConnection,
  type Connection,
  type GatewayEndpoint,
  type EnvActivationStyle,
  ENV_STYLES,
} from "../api/connections";

interface Props {
  initial?: Connection;
  onCancel: () => void;
  onSaved: () => void;
}

const EMPTY_GATEWAY: GatewayEndpoint = {
  host: "",
  user: "",
  port: 22,
  key_name: null,
  auth_method: "key",
};

const EMPTY_CONNECTION: Connection = {
  name: "",
  description: "",
  host: "",
  user: "",
  port: 22,
  key_name: "",
  gateway: null,
  work_dir: "/tmp/opalx-regsuite",
  cleanup_after_run: false,
  keepalive_interval: 30,
  env: { style: "none", module_use_paths: [], module_loads: [] },
};

const inputCls =
  "w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent";

export function ConnectionForm({ initial, onCancel, onSaved }: Props) {
  const isEdit = initial !== undefined;
  const queryClient = useQueryClient();

  const [form, setForm] = useState<Connection>(initial ?? EMPTY_CONNECTION);
  const [useGateway, setUseGateway] = useState<boolean>(initial?.gateway != null);
  const [error, setError] = useState<string | null>(null);

  const { data: keys } = useQuery<SshKeyInfo[]>({
    queryKey: ["ssh-keys"],
    queryFn: listSshKeys,
  });

  const saveMut = useMutation({
    mutationFn: (body: Connection) =>
      isEdit ? updateConnection(initial!.name, body) : createConnection(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      onSaved();
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else if (detail && typeof detail === "object" && "message" in detail) {
        setError(String((detail as { message: unknown }).message));
      } else {
        setError("Failed to save connection.");
      }
    },
  });

  function handleSubmit() {
    setError(null);
    if (!form.name.trim()) {
      setError("Connection name is required.");
      return;
    }
    if (!form.host.trim() || !form.user.trim() || !form.key_name) {
      setError("Host, user, and SSH key are required.");
      return;
    }
    if (useGateway) {
      if (!form.gateway?.host || !form.gateway?.user) {
        setError("Gateway host and user are required.");
        return;
      }
      if (form.gateway.auth_method === "key" && !form.gateway.key_name) {
        setError("Gateway SSH key is required for key-based authentication.");
        return;
      }
    }
    const body: Connection = {
      ...form,
      gateway: useGateway ? form.gateway : null,
    };
    saveMut.mutate(body);
  }

  function setEnvStyle(style: EnvActivationStyle) {
    setForm({ ...form, env: { ...form.env, style } });
  }

  const keyOptions = keys ?? [];

  return (
    <div className="bg-bg border border-border rounded-lg p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-fg text-base font-medium">
          {isEdit ? `Edit connection "${initial?.name}"` : "New connection"}
        </h3>
        <button
          onClick={onCancel}
          className="text-muted hover:text-fg transition p-1"
          title="Cancel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Name + description */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted mb-1">Name</label>
          <input
            type="text"
            placeholder="daint-cpu"
            value={form.name}
            disabled={isEdit}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
          <p className="text-muted text-xs mt-1">
            Avoid embedding usernames or hostnames here — this label is the only
            identity surface that may appear in publicly-shareable run logs.
          </p>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Description</label>
          <input
            type="text"
            placeholder="Optional"
            value={form.description ?? ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className={inputCls}
          />
        </div>
      </div>

      {/* SSH target */}
      <div className="border-t border-border pt-3">
        <h4 className="text-fg text-sm font-medium mb-2">SSH target</h4>
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label className="block text-xs text-muted mb-1">Host</label>
            <input
              type="text"
              placeholder="daint.alps.cscs.ch"
              value={form.host}
              onChange={(e) => setForm({ ...form, host: e.target.value })}
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Port</label>
            <input
              type="number"
              value={form.port}
              onChange={(e) =>
                setForm({ ...form, port: Number(e.target.value) || 22 })
              }
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">User</label>
            <input
              type="text"
              placeholder="aliemen"
              value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })}
              className={inputCls}
            />
          </div>
          <div className="col-span-2">
            <label className="block text-xs text-muted mb-1">SSH key</label>
            <select
              value={form.key_name}
              onChange={(e) => setForm({ ...form, key_name: e.target.value })}
              className={inputCls}
            >
              <option value="">— select a key —</option>
              {keyOptions.map((k) => (
                <option key={k.name}>{k.name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Gateway / ProxyJump */}
      <div className="border-t border-border pt-3">
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer">
          <input
            type="checkbox"
            checked={useGateway}
            onChange={(e) => {
              const enabled = e.target.checked;
              setUseGateway(enabled);
              if (enabled && !form.gateway) {
                setForm({ ...form, gateway: { ...EMPTY_GATEWAY } });
              }
            }}
            className="accent-accent"
          />
          Use SSH gateway (ProxyJump / hop)
        </label>

        {useGateway && form.gateway && (
          <div className="mt-3 flex flex-col gap-3">
            {/* Gateway auth method */}
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 text-sm text-muted cursor-pointer">
                <input
                  type="radio"
                  name="gw-auth"
                  checked={form.gateway.auth_method === "key"}
                  onChange={() =>
                    setForm({
                      ...form,
                      gateway: {
                        ...form.gateway!,
                        auth_method: "key",
                        key_name: form.gateway!.key_name ?? "",
                      },
                    })
                  }
                  className="accent-accent"
                />
                SSH key
              </label>
              <label className="flex items-center gap-1.5 text-sm text-muted cursor-pointer">
                <input
                  type="radio"
                  name="gw-auth"
                  checked={form.gateway.auth_method === "interactive"}
                  onChange={() =>
                    setForm({
                      ...form,
                      gateway: {
                        ...form.gateway!,
                        auth_method: "interactive",
                        key_name: null,
                      },
                    })
                  }
                  className="accent-accent"
                />
                Password + 2FA (keyboard-interactive)
              </label>
            </div>

            {/* Gateway host / port / user */}
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs text-muted mb-1">Gateway host</label>
                <input
                  type="text"
                  placeholder={
                    form.gateway.auth_method === "interactive"
                      ? "hopx.psi.ch"
                      : "ela.cscs.ch"
                  }
                  value={form.gateway.host}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      gateway: { ...form.gateway!, host: e.target.value },
                    })
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Gateway port</label>
                <input
                  type="number"
                  value={form.gateway.port}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      gateway: {
                        ...form.gateway!,
                        port: Number(e.target.value) || 22,
                      },
                    })
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Gateway user</label>
                <input
                  type="text"
                  value={form.gateway.user}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      gateway: { ...form.gateway!, user: e.target.value },
                    })
                  }
                  className={inputCls}
                />
              </div>

              {/* Gateway SSH key (key auth only) */}
              {form.gateway.auth_method === "key" ? (
                <div className="col-span-2">
                  <label className="block text-xs text-muted mb-1">
                    Gateway SSH key
                  </label>
                  <select
                    value={form.gateway.key_name ?? ""}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        gateway: { ...form.gateway!, key_name: e.target.value },
                      })
                    }
                    className={inputCls}
                  >
                    <option value="">— select a key —</option>
                    {keyOptions.map((k) => (
                      <option key={k.name}>{k.name}</option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="col-span-2">
                  <p className="text-muted text-xs bg-bg border border-border rounded-md px-3 py-2">
                    This gateway uses keyboard-interactive authentication (e.g.
                    hopx.psi.ch with Microsoft MFA). You will be prompted for
                    your password and authenticator OTP code each time you
                    trigger a run or test the connection. Credentials are used
                    once and never stored.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Workspace */}
      <div className="border-t border-border pt-3">
        <h4 className="text-fg text-sm font-medium mb-2">Workspace</h4>
        <div>
          <label className="block text-xs text-muted mb-1">Remote work directory</label>
          <input
            type="text"
            placeholder="/scratch/user/opalx-regsuite"
            value={form.work_dir}
            onChange={(e) => setForm({ ...form, work_dir: e.target.value })}
            className={inputCls}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted cursor-pointer mt-3">
          <input
            type="checkbox"
            checked={form.cleanup_after_run}
            onChange={(e) =>
              setForm({ ...form, cleanup_after_run: e.target.checked })
            }
            className="accent-accent"
          />
          Wipe work directory after every run
        </label>
      </div>

      {/* Environment activation */}
      <div className="border-t border-border pt-3">
        <h4 className="text-fg text-sm font-medium mb-2">Environment activation</h4>
        <div className="flex gap-4 mb-3">
          {ENV_STYLES.map((s) => (
            <label
              key={s}
              className="flex items-center gap-1.5 text-sm text-muted cursor-pointer"
            >
              <input
                type="radio"
                name="env-style"
                checked={form.env.style === s}
                onChange={() => setEnvStyle(s)}
                className="accent-accent"
              />
              {s}
            </label>
          ))}
        </div>

        {form.env.style === "modules" && (
          <div className="flex flex-col gap-2">
            <div>
              <label className="block text-xs text-muted mb-1">
                lmod init script
              </label>
              <input
                type="text"
                value={form.env.lmod_init ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    env: { ...form.env, lmod_init: e.target.value },
                  })
                }
                placeholder="/usr/share/lmod/lmod/init/bash"
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">
                module use paths (one per line)
              </label>
              <textarea
                rows={2}
                value={(form.env.module_use_paths ?? []).join("\n")}
                onChange={(e) =>
                  setForm({
                    ...form,
                    env: {
                      ...form.env,
                      module_use_paths: e.target.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    },
                  })
                }
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">
                module load (one per line, e.g. gcc/15.2.0)
              </label>
              <textarea
                rows={3}
                value={(form.env.module_loads ?? []).join("\n")}
                onChange={(e) =>
                  setForm({
                    ...form,
                    env: {
                      ...form.env,
                      module_loads: e.target.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    },
                  })
                }
                className={inputCls}
              />
            </div>
          </div>
        )}

        {form.env.style === "prologue" && (
          <div>
            <label className="block text-xs text-muted mb-1">Prologue command</label>
            <textarea
              rows={3}
              placeholder="source /opt/setup.sh"
              value={form.env.prologue ?? ""}
              onChange={(e) =>
                setForm({
                  ...form,
                  env: { ...form.env, prologue: e.target.value },
                })
              }
              className={`${inputCls} font-mono`}
            />
            <p className="text-muted text-xs mt-1">
              Shell command joined with <code className="text-fg">&&</code> before every remote command.
              Must keep <code className="text-fg">git</code>,{" "}
              <code className="text-fg">cmake</code>, and{" "}
              <code className="text-fg">make</code> available on PATH.
            </p>
          </div>
        )}

        {form.env.style === "uenv" && (
          <div>
            <label className="block text-xs text-muted mb-1">uenv run arguments</label>
            <textarea
              rows={3}
              placeholder="--view=develop /capstor/store/.../image.squashfs"
              value={form.env.prologue ?? ""}
              onChange={(e) =>
                setForm({
                  ...form,
                  env: { ...form.env, prologue: e.target.value },
                })
              }
              className={`${inputCls} font-mono`}
            />
            <p className="text-muted text-xs mt-1">
              Arguments placed between <code className="text-fg">uenv run</code> and{" "}
              <code className="text-fg">--</code>. Each command runs as{" "}
              <code className="text-fg">uenv run {"<args>"} -- {"<cmd>"}</code>.
              Use this instead of <code className="text-fg">uenv start</code>, which requires
              an interactive shell and fails in scripted SSH sessions.
            </p>
          </div>
        )}
      </div>

      {error && <p className="text-failed text-sm">{error}</p>}

      <div className="flex gap-2 justify-end border-t border-border pt-3">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm border border-border rounded-md text-muted hover:text-fg transition"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={saveMut.isPending}
          className="flex items-center gap-2 bg-accent text-bg font-medium rounded-md py-2 px-4 text-sm hover:brightness-110 transition disabled:opacity-50"
        >
          <Save size={15} />
          {saveMut.isPending ? "Saving..." : isEdit ? "Save changes" : "Create connection"}
        </button>
      </div>
    </div>
  );
}
