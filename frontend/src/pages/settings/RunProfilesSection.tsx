import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  Pencil,
  PlaySquare,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { listSshKeys } from "../../api/keys";
import {
  createRunProfile,
  deleteRunProfile,
  getExecutionSettings,
  listRunProfileSummaries,
  listRunProfiles,
  testRunProfile,
  updateRunProfile,
  type ProfileTestCredentials,
  type ProfileTestResult,
  type RunProfile,
} from "../../api/executionProfiles";

const EMPTY_PROFILE: RunProfile = {
  id: "",
  name: "",
  description: "",
  build_preset_id: "",
  machine_preset_id: "local",
  env_preset_id: null,
  slurm_preset_id: null,
  ssh_user: "",
  key_name: "",
  gateway_user: "",
  gateway_key_name: "",
  work_dir: "/tmp/opalx-regsuite",
  cleanup_after_run: false,
  keepalive_interval: 30,
  generated: false,
};

const inputCls =
  "w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent";

export function RunProfilesSection() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<RunProfile | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState<RunProfile>(EMPTY_PROFILE);
  const [error, setError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ProfileTestResult>>({});
  const [testCredsFor, setTestCredsFor] = useState<string | null>(null);
  const [testPassword, setTestPassword] = useState("");
  const [testOtp, setTestOtp] = useState("");

  const { data: settings } = useQuery({
    queryKey: ["execution-settings"],
    queryFn: getExecutionSettings,
  });
  const { data: profiles } = useQuery({
    queryKey: ["run-profiles"],
    queryFn: listRunProfiles,
  });
  const { data: summaries } = useQuery({
    queryKey: ["run-profile-summaries"],
    queryFn: listRunProfileSummaries,
  });
  const { data: keys } = useQuery({
    queryKey: ["ssh-keys"],
    queryFn: listSshKeys,
  });

  const selectedMachine = useMemo(
    () => settings?.machine_presets.find((m) => m.id === form.machine_preset_id) ?? null,
    [settings, form.machine_preset_id],
  );
  const selectedGateway = selectedMachine?.gateway ?? null;
  const keyOptions = keys ?? [];

  const saveMut = useMutation({
    mutationFn: (body: RunProfile) =>
      editing ? updateRunProfile(editing.id, body) : createRunProfile(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["run-profile-summaries"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles-trigger"] });
      closeForm();
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      if (typeof detail === "string") setError(detail);
      else if (detail && typeof detail === "object" && "message" in detail) {
        setError(String((detail as { message: unknown }).message));
      } else setError("Failed to save run profile.");
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteRunProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["run-profile-summaries"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles-trigger"] });
    },
  });

  const testMut = useMutation({
    mutationFn: ({
      id,
      credentials,
    }: {
      id: string;
      credentials?: ProfileTestCredentials;
    }) => testRunProfile(id, credentials),
    onSuccess: (result, { id }) => {
      setTestResults((prev) => ({ ...prev, [id]: result }));
      setTestCredsFor(null);
      setTestPassword("");
      setTestOtp("");
    },
    onError: (e: unknown, { id }) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: false, error: detail ?? "Test failed." },
      }));
    },
  });

  function openNew() {
    const firstBuild = settings?.build_presets[0]?.id ?? "";
    setForm({
      ...EMPTY_PROFILE,
      build_preset_id: firstBuild,
      machine_preset_id: settings?.machine_presets[0]?.id ?? "local",
    });
    setEditing(null);
    setShowNew(true);
    setError(null);
  }

  function openEdit(profile: RunProfile) {
    setForm(profile);
    setEditing(profile);
    setShowNew(false);
    setError(null);
  }

  function closeForm() {
    setEditing(null);
    setShowNew(false);
    setForm(EMPTY_PROFILE);
    setError(null);
  }

  function submit() {
    setError(null);
    if (!form.id.trim() || !form.name.trim()) {
      setError("ID and name are required.");
      return;
    }
    if (!form.build_preset_id || !form.machine_preset_id) {
      setError("Build and machine presets are required.");
      return;
    }
    if (selectedMachine?.kind === "ssh") {
      if (!form.ssh_user?.trim() || !form.key_name) {
        setError("SSH user and key are required for SSH machines.");
        return;
      }
      if (!form.work_dir.trim()) {
        setError("Remote work directory is required.");
        return;
      }
      if (selectedGateway && !form.gateway_user?.trim()) {
        setError("Gateway user is required.");
        return;
      }
      if (selectedGateway?.auth_method === "key" && !form.gateway_key_name) {
        setError("Gateway key is required for key-auth gateways.");
        return;
      }
    }
    saveMut.mutate({
      ...form,
      description: form.description || null,
      env_preset_id: form.env_preset_id || null,
      slurm_preset_id: selectedMachine?.kind === "local" ? null : form.slurm_preset_id || null,
      ssh_user: selectedMachine?.kind === "ssh" ? form.ssh_user || null : null,
      key_name: selectedMachine?.kind === "ssh" ? form.key_name || null : null,
      gateway_user: selectedGateway ? form.gateway_user || null : null,
      gateway_key_name:
        selectedGateway?.auth_method === "key" ? form.gateway_key_name || null : null,
    });
  }

  const activeForm = showNew || editing;

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6">
      <div className="flex flex-col gap-3 mb-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <PlaySquare size={18} />
          Run profiles
        </h2>
        {!activeForm && (
          <button
            type="button"
            onClick={openNew}
            className="flex items-center gap-1.5 text-sm text-accent hover:brightness-110 transition border border-accent/50 rounded-md px-3 py-1.5"
          >
            <Plus size={14} />
            Add profile
          </button>
        )}
      </div>
      <p className="text-muted text-sm mb-5">
        Private profiles combine public execution presets with your username,
        SSH keys, and workspace path.
      </p>

      {activeForm && (
        <div className="bg-bg border border-border rounded-lg p-4 mb-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h3 className="text-fg text-base font-medium">
              {editing ? `Edit "${editing.name}"` : "New run profile"}
            </h3>
            <button type="button" onClick={closeForm} className="text-muted hover:text-fg">
              <X size={16} />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-muted mb-1">ID</label>
              <input
                value={form.id}
                disabled={!!editing}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className={inputCls}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs text-muted mb-1">Description</label>
              <input
                value={form.description ?? ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Build preset</label>
              <select
                value={form.build_preset_id}
                onChange={(e) => setForm({ ...form, build_preset_id: e.target.value })}
                className={inputCls}
              >
                <option value="">Select build</option>
                {(settings?.build_presets ?? []).map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Machine preset</label>
              <select
                value={form.machine_preset_id}
                onChange={(e) =>
                  setForm({
                    ...form,
                    machine_preset_id: e.target.value,
                    slurm_preset_id:
                      settings?.machine_presets.find((m) => m.id === e.target.value)?.kind ===
                      "local"
                        ? null
                        : form.slurm_preset_id,
                  })
                }
                className={inputCls}
              >
                {(settings?.machine_presets ?? []).map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted mb-1">Environment preset</label>
              <select
                value={form.env_preset_id ?? ""}
                onChange={(e) => setForm({ ...form, env_preset_id: e.target.value || null })}
                className={inputCls}
              >
                <option value="">None</option>
                {(settings?.env_presets ?? []).map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </div>
            {selectedMachine?.kind === "ssh" && (
              <div>
                <label className="block text-xs text-muted mb-1">Slurm preset</label>
                <select
                  value={form.slurm_preset_id ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, slurm_preset_id: e.target.value || null })
                  }
                  className={inputCls}
                >
                  <option value="">None</option>
                  {(settings?.slurm_presets ?? []).map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {selectedMachine?.kind === "ssh" && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs text-muted mb-1">SSH user</label>
                <input
                  value={form.ssh_user ?? ""}
                  onChange={(e) => setForm({ ...form, ssh_user: e.target.value })}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">SSH key</label>
                <select
                  value={form.key_name ?? ""}
                  onChange={(e) => setForm({ ...form, key_name: e.target.value })}
                  className={inputCls}
                >
                  {form.key_name && !keyOptions.some((k) => k.name === form.key_name) && (
                    <option value={form.key_name}>{form.key_name} (missing)</option>
                  )}
                  <option value="">Select key</option>
                  {keyOptions.map((key) => (
                    <option key={key.name}>{key.name}</option>
                  ))}
                </select>
              </div>
              {selectedGateway && (
                <>
                  <div>
                    <label className="block text-xs text-muted mb-1">Gateway user</label>
                    <input
                      value={form.gateway_user ?? ""}
                      onChange={(e) =>
                        setForm({ ...form, gateway_user: e.target.value })
                      }
                      className={inputCls}
                    />
                  </div>
                  {selectedGateway.auth_method === "key" && (
                    <div>
                      <label className="block text-xs text-muted mb-1">Gateway key</label>
                      <select
                        value={form.gateway_key_name ?? ""}
                        onChange={(e) =>
                          setForm({ ...form, gateway_key_name: e.target.value })
                        }
                        className={inputCls}
                      >
                        {form.gateway_key_name &&
                          !keyOptions.some((k) => k.name === form.gateway_key_name) && (
                            <option value={form.gateway_key_name}>
                              {form.gateway_key_name} (missing)
                            </option>
                          )}
                        <option value="">Select key</option>
                        {keyOptions.map((key) => (
                          <option key={key.name}>{key.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              )}
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted mb-1">Remote work directory</label>
                <input
                  value={form.work_dir}
                  onChange={(e) => setForm({ ...form, work_dir: e.target.value })}
                  className={inputCls}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
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
          )}

          {error && <p className="text-failed text-sm">{error}</p>}
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <button
              type="button"
              onClick={closeForm}
              className="px-4 py-2 text-sm border border-border rounded-md text-muted hover:text-fg"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={saveMut.isPending}
              className="px-4 py-2 text-sm bg-accent text-bg font-medium rounded-md hover:brightness-110 disabled:opacity-50"
            >
              {saveMut.isPending ? "Saving..." : editing ? "Save" : "Create"}
            </button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[50rem] text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-left">
              <th className="pb-2 font-medium">Profile</th>
              <th className="pb-2 font-medium">Build</th>
              <th className="pb-2 font-medium">Machine</th>
              <th className="pb-2 font-medium">Env</th>
              <th className="pb-2 font-medium">Slurm</th>
              <th className="pb-2 font-medium w-32"></th>
            </tr>
          </thead>
          <tbody>
            {(profiles ?? []).map((profile) => {
              const summary = summaries?.find((item) => item.id === profile.id);
              const result = testResults[profile.id];
              return (
                <tr key={profile.id} className="border-b border-border last:border-0">
                  <td className="py-2.5 text-fg">
                    <div className="font-mono">{profile.name}</div>
                    <div className="text-muted text-xs">{profile.id}</div>
                    {summary && !summary.valid && (
                      <div className="text-failed text-xs">
                        {summary.validation_errors.join("; ")}
                      </div>
                    )}
                    {result && (
                      <div className={result.ok ? "text-passed text-xs" : "text-failed text-xs"}>
                        {result.ok ? `OK${result.whoami ? ` (${result.whoami})` : ""}` : result.error}
                      </div>
                    )}
                    {testCredsFor === profile.id && (
                      <div className="mt-2 flex gap-2">
                        <input
                          type="password"
                          placeholder="Password"
                          value={testPassword}
                          onChange={(e) => setTestPassword(e.target.value)}
                          className="min-w-0 flex-1 bg-bg border border-border rounded-md px-2 py-1 text-xs text-fg"
                        />
                        <input
                          placeholder="OTP"
                          value={testOtp}
                          onChange={(e) => setTestOtp(e.target.value)}
                          className="w-20 bg-bg border border-border rounded-md px-2 py-1 text-xs text-fg"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            testMut.mutate({
                              id: profile.id,
                              credentials: {
                                gateway_password: testPassword,
                                gateway_otp: testOtp,
                              },
                            })
                          }
                          className="text-xs text-accent"
                        >
                          Test
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 text-muted text-xs">
                    {summary?.build_preset_name ?? profile.build_preset_id}
                  </td>
                  <td className="py-2.5 text-muted text-xs">
                    {summary?.machine_preset_name ?? profile.machine_preset_id}
                  </td>
                  <td className="py-2.5 text-muted text-xs">
                    {summary?.env_preset_name ?? summary?.env_style ?? "none"}
                  </td>
                  <td className="py-2.5 text-muted text-xs">
                    {summary?.slurm_preset_name ?? "none"}
                  </td>
                  <td className="py-2.5">
                    <div className="flex justify-end gap-1">
                      {result?.ok ? (
                        <Check size={14} className="text-passed mt-1" />
                      ) : result ? (
                        <AlertCircle size={14} className="text-failed mt-1" />
                      ) : null}
                      <button
                        type="button"
                        disabled={testMut.isPending || summary?.valid === false}
                        onClick={() => {
                          if (summary?.interactive_gateway) {
                            setTestCredsFor(profile.id);
                            setTestPassword("");
                            setTestOtp("");
                          } else {
                            testMut.mutate({ id: profile.id });
                          }
                        }}
                        className="text-muted hover:text-accent p-1 disabled:opacity-40"
                        title="Test profile"
                      >
                        <Zap size={15} />
                      </button>
                      <button
                        type="button"
                        onClick={() => openEdit(profile)}
                        className="text-muted hover:text-fg p-1"
                        title="Edit"
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        disabled={deleteMut.isPending}
                        onClick={() => deleteMut.mutate(profile.id)}
                        className="text-muted hover:text-failed p-1 disabled:opacity-40"
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
      </div>
    </div>
  );
}

