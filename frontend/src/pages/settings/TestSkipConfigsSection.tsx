import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import {
  createSkipConfig,
  deleteSkipConfig,
  getSkipCandidates,
  listSkipConfigs,
  skipSummary,
  updateSkipConfig,
  type SkipConfig,
  type SkipConfigInput,
} from "../../api/skipConfigs";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SkipTestPicker } from "./SkipTestPicker";

const EMPTY: SkipConfigInput = {
  name: "",
  description: null,
  unit_tests: [],
  regression_tests: [],
};

function errorDetail(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join("; ");
  }
  return "Saving the skip config failed.";
}

/**
 * Global test skip configs. A config is only applied when picked on Start Run;
 * schedules always run every test.
 */
export function TestSkipConfigsSection() {
  const queryClient = useQueryClient();
  const { data: configs, isLoading } = useQuery({
    queryKey: ["skip-configs"],
    queryFn: listSkipConfigs,
  });
  const { data: candidates } = useQuery({
    queryKey: ["skip-candidates"],
    queryFn: getSkipCandidates,
  });
  const [editing, setEditing] = useState<{ id: string | null; draft: SkipConfigInput } | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<SkipConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const saveMut = useMutation({
    mutationFn: ({ id, draft }: { id: string | null; draft: SkipConfigInput }) =>
      id ? updateSkipConfig(id, draft) : createSkipConfig(draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skip-configs"] });
      setEditing(null);
      setError(null);
    },
    onError: (e) => setError(errorDetail(e)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSkipConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["skip-configs"] }),
  });

  function startEdit(config: SkipConfig | null) {
    setError(null);
    setEditing(
      config
        ? {
            id: config.id,
            draft: {
              name: config.name,
              description: config.description ?? null,
              unit_tests: config.unit_tests,
              regression_tests: config.regression_tests,
            },
          }
        : { id: null, draft: EMPTY },
    );
  }

  function updateDraft(patch: Partial<SkipConfigInput>) {
    setEditing((prev) => (prev ? { ...prev, draft: { ...prev.draft, ...patch } } : prev));
  }

  function save() {
    if (!editing) return;
    if (!editing.draft.name.trim()) {
      setError("Name is required.");
      return;
    }
    saveMut.mutate({
      id: editing.id,
      draft: {
        ...editing.draft,
        name: editing.draft.name.trim(),
        description: editing.draft.description?.trim() || null,
      },
    });
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-fg font-medium">Test Skip Configs</h2>
          <p className="text-muted text-xs mt-1">
            Named lists of tests to skip. Pick one on Start Run; scheduled runs always
            run every test.
          </p>
        </div>
        {!editing && (
          <button
            type="button"
            onClick={() => startEdit(null)}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm text-bg"
          >
            <Plus size={14} />
            New skip config
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-3">
          <label className="block text-sm text-muted">
            Name
            <input
              value={editing.draft.name}
              onChange={(e) => updateDraft({ name: e.target.value })}
              className="mt-1 w-full bg-bg border border-border rounded-md px-3 py-2 text-sm text-fg focus:outline-none focus:border-accent"
            />
          </label>
          <label className="block text-sm text-muted">
            Description
            <input
              value={editing.draft.description ?? ""}
              onChange={(e) => updateDraft({ description: e.target.value })}
              className="mt-1 w-full bg-bg border border-border rounded-md px-3 py-2 text-sm text-fg focus:outline-none focus:border-accent"
            />
          </label>
          <div className="grid gap-3 md:grid-cols-2">
            <SkipTestPicker
              title="Regression tests"
              noun="regression test"
              candidates={candidates?.regression ?? []}
              selected={editing.draft.regression_tests}
              onChange={(next) => updateDraft({ regression_tests: next })}
            />
            <SkipTestPicker
              title="Unit tests"
              noun="unit test"
              candidates={candidates?.unit ?? []}
              selected={editing.draft.unit_tests}
              onChange={(next) => updateDraft({ unit_tests: next })}
            />
          </div>
          {error && <p className="text-failed text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setEditing(null)}
              className="rounded-md border border-border px-4 py-1.5 text-sm text-muted hover:text-fg"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saveMut.isPending}
              className="rounded-md bg-accent px-4 py-1.5 text-sm text-bg disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </div>
      ) : isLoading ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : (configs ?? []).length === 0 ? (
        <p className="text-muted text-sm">No skip configs yet.</p>
      ) : (
        <ul className="space-y-2">
          {(configs ?? []).map((config) => (
            <li
              key={config.id}
              className="flex items-start justify-between gap-3 rounded-lg border border-border px-3 py-2"
            >
              <div className="min-w-0">
                <p className="text-fg text-sm">{config.name}</p>
                {config.description && (
                  <p className="text-muted text-xs">{config.description}</p>
                )}
                <p className="text-muted text-xs mt-0.5">{skipSummary(config)}</p>
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label={`Edit ${config.name}`}
                  onClick={() => startEdit(config)}
                  className="rounded-md p-1.5 text-muted hover:text-fg"
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${config.name}`}
                  onClick={() => setDeleteTarget(config)}
                  className="rounded-md p-1.5 text-muted hover:text-failed"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete skip config"
        message={`Delete "${deleteTarget?.name ?? ""}"? Past runs keep their recorded skips.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => {
          if (deleteTarget) deleteMut.mutate(deleteTarget.id);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
