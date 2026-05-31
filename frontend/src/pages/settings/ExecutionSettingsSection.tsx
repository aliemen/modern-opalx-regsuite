import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, RotateCcw, Save } from "lucide-react";
import {
  getExecutionSettings,
  resetExecutionSettingsFromConfig,
  saveExecutionSettings,
  type ExecutionSettings,
} from "../../api/executionProfiles";

const textCls =
  "w-full min-h-40 resize-y bg-bg border border-border rounded-md px-3 py-2 text-fg text-xs font-mono focus:outline-none focus:border-accent";

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function ExecutionSettingsSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["execution-settings"],
    queryFn: getExecutionSettings,
  });

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6">
      {isLoading || !data ? (
        <>
          <Header />
          <p className="text-muted text-sm">Loading execution settings...</p>
        </>
      ) : (
        <ExecutionSettingsEditor
          key={data.modified_at ?? data.created_at ?? "loaded"}
          initial={data}
        />
      )}
    </div>
  );
}

function Header() {
  return (
    <>
      <div className="flex flex-col gap-3 mb-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <Database size={18} />
          Public execution settings
        </h2>
      </div>
      <p className="text-muted text-sm mb-4">
        Shared build, machine, environment, and Slurm presets. These definitions
        are visible to every dashboard user and may be referenced by private run
        profiles.
      </p>
    </>
  );
}

function ExecutionSettingsEditor({ initial }: { initial: ExecutionSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => pretty(initial));
  const [error, setError] = useState<string | null>(null);

  const saveMut = useMutation({
    mutationFn: (body: ExecutionSettings) => saveExecutionSettings(body),
    onSuccess: (saved) => {
      setError(null);
      setDraft(pretty(saved));
      queryClient.invalidateQueries({ queryKey: ["execution-settings"] });
      queryClient.invalidateQueries({ queryKey: ["run-profile-summaries"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles-trigger"] });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail ?? "Failed to save execution settings.");
    },
  });

  const resetMut = useMutation({
    mutationFn: resetExecutionSettingsFromConfig,
    onSuccess: (saved) => {
      setError(null);
      setDraft(pretty(saved));
      queryClient.invalidateQueries({ queryKey: ["execution-settings"] });
      queryClient.invalidateQueries({ queryKey: ["run-profile-summaries"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["run-profiles-trigger"] });
    },
  });

  function handleSave() {
    setError(null);
    try {
      saveMut.mutate(JSON.parse(draft) as ExecutionSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid JSON.");
    }
  }

  return (
    <>
      <div className="flex flex-col gap-3 mb-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <Database size={18} />
          Public execution settings
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => resetMut.mutate()}
            disabled={resetMut.isPending}
            className="flex items-center gap-1.5 text-sm text-muted hover:text-fg transition border border-border rounded-md px-3 py-1.5 disabled:opacity-50"
          >
            <RotateCcw size={14} />
            Reset
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveMut.isPending}
            className="flex items-center gap-1.5 text-sm bg-accent text-bg font-medium rounded-md px-3 py-1.5 hover:brightness-110 transition disabled:opacity-50"
          >
            <Save size={14} />
            Save
          </button>
        </div>
      </div>
      <p className="text-muted text-sm mb-4">
        Shared build, machine, environment, and Slurm presets. These definitions
        are visible to every dashboard user and may be referenced by private run
        profiles.
      </p>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        className={textCls}
      />
      {error && <p className="text-failed text-sm mt-3">{error}</p>}
    </>
  );
}
