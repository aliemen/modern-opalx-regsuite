/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, ShieldAlert } from "lucide-react";
import {
  getArchConfigs,
  getOpalxBranches,
  getRegtestsBranches,
} from "../../api/runs";
import { listConnections, LOCAL_CONNECTION } from "../../api/connections";
import type {
  DayOfWeek,
  Schedule,
  ScheduleWriteBody,
} from "../../api/schedules";
import { DayPicker } from "./DayPicker";

interface ScheduleFormModalProps {
  open: boolean;
  initial: Schedule | null;
  onClose: () => void;
  onSubmit: (body: ScheduleWriteBody) => Promise<void>;
  busy?: boolean;
}

function defaultBody(): ScheduleWriteBody {
  return {
    name: "",
    enabled: true,
    spec: { days: ["MON"], time: "02:00" },
    branch: "master",
    arch: "cpu-serial",
    regtests_branch: "master",
    connection_name: LOCAL_CONNECTION,
    skip_unit: false,
    skip_regression: false,
    clean_build: false,
    public: false,
  };
}

function scheduleToBody(schedule: Schedule): ScheduleWriteBody {
  return {
    name: schedule.name,
    enabled: schedule.enabled,
    spec: { days: schedule.spec.days, time: schedule.spec.time },
    branch: schedule.branch,
    arch: schedule.arch,
    regtests_branch: schedule.regtests_branch ?? "master",
    connection_name: schedule.connection_name,
    skip_unit: schedule.skip_unit,
    skip_regression: schedule.skip_regression,
    clean_build: schedule.clean_build,
    public: schedule.public,
  };
}

export function ScheduleFormModal({
  open,
  initial,
  onClose,
  onSubmit,
  busy,
}: ScheduleFormModalProps) {
  const [form, setForm] = useState<ScheduleWriteBody>(defaultBody);
  const [error, setError] = useState<string | null>(null);

  // Reset form every time the modal opens with fresh data.
  useEffect(() => {
    if (!open) return;
    setForm(initial ? scheduleToBody(initial) : defaultBody());
    setError(null);
  }, [open, initial]);

  const { data: opalxBranches } = useQuery({
    queryKey: ["opalx-branches"],
    queryFn: getOpalxBranches,
    enabled: open,
  });
  const { data: regtestsBranches } = useQuery({
    queryKey: ["regtests-branches"],
    queryFn: getRegtestsBranches,
    enabled: open,
  });
  const { data: archConfigs } = useQuery({
    queryKey: ["arch-configs"],
    queryFn: getArchConfigs,
    enabled: open,
  });
  const { data: connections } = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
    enabled: open,
  });

  const selectedConnection = useMemo(
    () =>
      form.connection_name === LOCAL_CONNECTION
        ? null
        : connections?.find((c) => c.name === form.connection_name) ?? null,
    [connections, form.connection_name],
  );
  const selectedIs2fa =
    selectedConnection?.gateway?.auth_method === "interactive";

  function updateField<K extends keyof ScheduleWriteBody>(
    key: K,
    value: ScheduleWriteBody[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function updateDays(days: DayOfWeek[]) {
    setForm((prev) => ({ ...prev, spec: { ...prev.spec, days } }));
  }

  function updateTime(time: string) {
    setForm((prev) => ({ ...prev, spec: { ...prev.spec, time } }));
  }

  async function handleSubmit() {
    setError(null);
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (form.spec.days.length === 0) {
      setError("Select at least one day.");
      return;
    }
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(form.spec.time)) {
      setError("Time must be HH:MM in 24-hour format.");
      return;
    }
    if (selectedIs2fa) {
      setError(
        "This connection uses a 2FA gateway — scheduled runs cannot supply OTPs.",
      );
      return;
    }
    try {
      await onSubmit(form);
      onClose();
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to save schedule.";
      setError(msg);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h2 className="text-fg text-lg font-semibold">
            {initial ? "Edit schedule" : "New schedule"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-muted hover:text-fg"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-4">
          <div>
            <label className="block text-sm text-muted mb-1">Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              placeholder="e.g. Nightly master"
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="block text-sm text-muted mb-1">Days</label>
            <DayPicker value={form.spec.days} onChange={updateDays} />
          </div>

          <div>
            <label className="block text-sm text-muted mb-1">
              Time (server-local)
            </label>
            <input
              type="time"
              value={form.spec.time}
              onChange={(e) => updateTime(e.target.value)}
              className="bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-sm text-muted mb-1">
                OPALX branch
              </label>
              <select
                value={form.branch}
                onChange={(e) => updateField("branch", e.target.value)}
                className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              >
                {(opalxBranches ?? [form.branch]).map((b) => (
                  <option key={b}>{b}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">
                Regtests branch
              </label>
              <select
                value={form.regtests_branch ?? "master"}
                onChange={(e) => updateField("regtests_branch", e.target.value)}
                className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              >
                {(regtestsBranches ?? [form.regtests_branch ?? "master"]).map(
                  (b) => (
                    <option key={b}>{b}</option>
                  ),
                )}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm text-muted mb-1">Run config</label>
            <select
              value={form.arch}
              onChange={(e) => updateField("arch", e.target.value)}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            >
              {(archConfigs ?? [form.arch]).map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm text-muted mb-1">Connection</label>
            <select
              value={form.connection_name}
              onChange={(e) => updateField("connection_name", e.target.value)}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            >
              <option value={LOCAL_CONNECTION}>Local</option>
              {(connections ?? []).map((c) => {
                const is2fa = c.gateway?.auth_method === "interactive";
                return (
                  <option key={c.name} value={c.name} disabled={is2fa}>
                    {c.name}
                    {c.description ? ` - ${c.description}` : ""}
                    {is2fa ? " (2FA - not supported)" : ""}
                  </option>
                );
              })}
            </select>
            {selectedIs2fa && (
              <div className="flex items-start gap-2 text-xs text-failed mt-2">
                <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                <span>
                  Scheduled runs cannot use 2FA gateways (OTPs expire before
                  the run starts).
                </span>
              </div>
            )}
            <p className="text-muted text-xs mt-1">
              Only your own connections are listed. Other users' connections
              remain private.
            </p>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={form.skip_unit}
                onChange={(e) => updateField("skip_unit", e.target.checked)}
                className="accent-accent"
              />
              Skip unit tests
            </label>
            <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={form.skip_regression}
                onChange={(e) => updateField("skip_regression", e.target.checked)}
                className="accent-accent"
              />
              Skip regression tests
            </label>
            <label
              className="flex items-center gap-2 text-sm text-muted cursor-pointer"
              title="Delete the build directory before cmake + make on every fire. Forces a full reconfigure and recompile."
            >
              <input
                type="checkbox"
                checked={form.clean_build}
                onChange={(e) => updateField("clean_build", e.target.checked)}
                className="accent-accent"
              />
              Clean build
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={form.public}
              onChange={(e) => updateField("public", e.target.checked)}
              className="accent-accent"
            />
            Publish runs automatically
          </label>
          <p className="text-muted text-xs -mt-2 ml-6">
            Runs produced by this schedule will be visible on the public
            landing page.
          </p>

          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => updateField("enabled", e.target.checked)}
              className="accent-accent"
            />
            Enabled (uncheck to pause without deleting)
          </label>

          {error && <p className="text-failed text-sm">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 p-5 border-t border-border">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-muted hover:text-fg border border-border rounded-md"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={busy}
            className="px-4 py-2 text-sm bg-accent text-bg font-medium rounded-md hover:brightness-110 disabled:opacity-60"
          >
            {busy ? "Saving..." : initial ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
