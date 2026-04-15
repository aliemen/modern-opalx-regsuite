import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, CalendarClock, AlertTriangle } from "lucide-react";
import { getCurrentUser } from "../api/user";
import type { Schedule, ScheduleWriteBody } from "../api/schedules";
import { getSchedulerStatus } from "../api/schedules";
import { useScheduleMutations, useSchedulesQuery } from "../hooks/useSchedules";
import { ScheduleCard } from "../components/schedule/ScheduleCard";
import { ScheduleFormModal } from "../components/schedule/ScheduleFormModal";
import { ConfirmDialog } from "../components/ConfirmDialog";

export function SchedulePage() {
  const { data: schedules, isLoading, error } = useSchedulesQuery();
  const { data: me } = useQuery({
    queryKey: ["auth-me"],
    queryFn: getCurrentUser,
  });
  const { data: schedulerStatus } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: getSchedulerStatus,
    refetchInterval: 60_000,
  });
  const { createMut, updateMut, toggleMut, deleteMut } = useScheduleMutations();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Schedule | null>(null);

  function openNew() {
    setEditing(null);
    setModalOpen(true);
  }

  function openEdit(schedule: Schedule) {
    setEditing(schedule);
    setModalOpen(true);
  }

  async function handleSubmit(body: ScheduleWriteBody) {
    if (editing) {
      await updateMut.mutateAsync({ id: editing.id, body });
    } else {
      await createMut.mutateAsync(body);
    }
  }

  async function handleConfirmDelete() {
    if (!confirmDelete) return;
    await deleteMut.mutateAsync(confirmDelete.id);
    setConfirmDelete(null);
  }

  const loadError =
    (error as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail ?? null;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-fg text-2xl font-semibold flex items-center gap-2">
            <CalendarClock size={24} />
            Schedule
          </h1>
          <p className="text-muted text-sm mt-1">
            Weekly recurring runs, visible to all users. Create one for each
            branch/arch combination you want tested on a cadence.
          </p>
        </div>
        <button
          type="button"
          onClick={openNew}
          className="flex items-center gap-2 bg-accent text-bg font-medium rounded-md px-4 py-2 text-sm hover:brightness-110 transition"
        >
          <Plus size={15} />
          New schedule
        </button>
      </div>

      {schedulerStatus && !schedulerStatus.running && (
        <div className="flex items-start gap-3 bg-surface border border-yellow-500/40 text-yellow-400 rounded-xl px-4 py-3 mb-4 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            <strong>Scheduler is not running.</strong> Schedules will not fire
            until the server is restarted with a valid config. Check the server
            logs for a config load error.
          </span>
        </div>
      )}

      {isLoading && (
        <p className="text-muted text-sm">Loading schedules...</p>
      )}

      {loadError && (
        <p className="text-failed text-sm mb-4">{loadError}</p>
      )}

      {schedules && schedules.length === 0 && !isLoading && (
        <div className="bg-surface border border-border rounded-xl p-8 text-center">
          <CalendarClock size={28} className="mx-auto text-muted mb-2" />
          <p className="text-muted text-sm">
            No schedules yet. Click{" "}
            <span className="text-fg">New schedule</span> to create one.
          </p>
        </div>
      )}

      {schedules && schedules.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {schedules.map((s) => (
            <ScheduleCard
              key={s.id}
              schedule={s}
              currentUser={me?.username ?? null}
              onEdit={() => openEdit(s)}
              onToggle={() => toggleMut.mutate(s.id)}
              onDelete={() => setConfirmDelete(s)}
              toggleBusy={toggleMut.isPending && toggleMut.variables === s.id}
              deleteBusy={deleteMut.isPending && deleteMut.variables === s.id}
            />
          ))}
        </div>
      )}

      <ScheduleFormModal
        open={modalOpen}
        initial={editing}
        onClose={() => setModalOpen(false)}
        onSubmit={handleSubmit}
        busy={createMut.isPending || updateMut.isPending}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete schedule?"
        message={
          confirmDelete
            ? `Delete "${confirmDelete.name}" (owned by ${confirmDelete.owner})? This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
