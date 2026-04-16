import { Clock, Calendar, Pencil, Trash2, Power, User } from "lucide-react";
import {
  DAYS_ORDERED,
  DAY_LABEL,
  type Schedule,
} from "../../api/schedules";

interface ScheduleCardProps {
  schedule: Schedule;
  currentUser: string | null;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  toggleBusy?: boolean;
  deleteBusy?: boolean;
}

function formatDays(days: Schedule["spec"]["days"]): string {
  if (days.length === 7) return "Every day";
  if (
    days.length === 5 &&
    ["MON", "TUE", "WED", "THU", "FRI"].every((d) =>
      days.includes(d as (typeof days)[number]),
    )
  ) {
    return "Weekdays";
  }
  if (
    days.length === 2 &&
    days.includes("SAT") &&
    days.includes("SUN")
  ) {
    return "Weekends";
  }
  return DAYS_ORDERED.filter((d) => days.includes(d))
    .map((d) => DAY_LABEL[d])
    .join(", ");
}

function formatLastStatus(status: string | null | undefined): {
  label: string;
  className: string;
} {
  if (!status) return { label: "Never triggered", className: "text-muted" };
  switch (status) {
    case "started":
      return { label: "Last: started", className: "text-accent" };
    case "queued":
      return { label: "Last: queued", className: "text-accent" };
    case "skipped_2fa":
      return { label: "Last: skipped (2FA)", className: "text-failed" };
    case "missing_connection":
      return { label: "Last: missing connection", className: "text-failed" };
    case "missing_key":
      return { label: "Last: missing SSH key", className: "text-failed" };
    case "busy_interactive":
      return { label: "Last: busy (2FA)", className: "text-failed" };
    case "error":
      return { label: "Last: error", className: "text-failed" };
    default:
      return { label: `Last: ${status}`, className: "text-muted" };
  }
}

export function ScheduleCard({
  schedule,
  currentUser,
  onEdit,
  onToggle,
  onDelete,
  toggleBusy,
  deleteBusy,
}: ScheduleCardProps) {
  const isOwner = currentUser !== null && schedule.owner === currentUser;
  const lastStatus = formatLastStatus(schedule.last_status);
  const daysLabel = formatDays(schedule.spec.days);

  return (
    <div
      className={
        "bg-surface border rounded-xl p-4 flex flex-col gap-3 " +
        (schedule.enabled ? "border-border" : "border-border/50 opacity-70")
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-fg font-medium truncate">{schedule.name}</h3>
            {!schedule.enabled && (
              <span className="text-xs text-muted border border-border rounded px-1.5 py-0.5">
                Paused
              </span>
            )}
          </div>
          <p className="text-xs text-muted flex items-center gap-1 mt-0.5">
            <User size={12} />
            {schedule.owner}
          </p>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={onToggle}
            disabled={!isOwner || toggleBusy}
            title={
              isOwner
                ? schedule.enabled
                  ? "Pause schedule"
                  : "Resume schedule"
                : `Only ${schedule.owner} can toggle this schedule`
            }
            className="p-1.5 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Power size={14} />
          </button>
          <button
            type="button"
            onClick={onEdit}
            disabled={!isOwner}
            title={
              isOwner
                ? "Edit schedule"
                : `Only ${schedule.owner} can edit this schedule`
            }
            className="p-1.5 text-muted hover:text-fg border border-border rounded-md transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Pencil size={14} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleteBusy}
            title="Delete schedule (any user)"
            className="p-1.5 text-muted hover:text-failed border border-border rounded-md transition disabled:opacity-40"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted">
        <div className="flex items-center gap-1.5">
          <Calendar size={12} />
          <span className="text-fg">{daysLabel}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock size={12} />
          <span className="text-fg">{schedule.spec.time}</span>
          <span className="text-muted">(server-local)</span>
        </div>
        <div className="truncate">
          OPALX: <span className="text-fg">{schedule.branch}</span>
        </div>
        <div className="truncate">
          Regtests:{" "}
          <span className="text-fg">
            {schedule.regtests_branch || "master"}
          </span>
        </div>
        <div className="truncate">
          Arch: <span className="text-fg">{schedule.arch}</span>
        </div>
        <div className="truncate">
          Connection: <span className="text-fg">{schedule.connection_name}</span>
        </div>
      </div>

      {(schedule.skip_unit ||
        schedule.skip_regression ||
        schedule.clean_build) && (
        <div className="flex gap-2 text-[11px] text-muted">
          {schedule.skip_unit && (
            <span className="px-1.5 py-0.5 border border-border rounded">
              skip unit
            </span>
          )}
          {schedule.skip_regression && (
            <span className="px-1.5 py-0.5 border border-border rounded">
              skip regression
            </span>
          )}
          {schedule.clean_build && (
            <span
              className="px-1.5 py-0.5 border border-border rounded"
              title="Wipes the build directory before cmake on every fire"
            >
              clean build
            </span>
          )}
        </div>
      )}

      <div className="flex items-center justify-between text-[11px] border-t border-border pt-2">
        <span className={lastStatus.className}>{lastStatus.label}</span>
        {schedule.last_triggered_at && (
          <span className="text-muted">
            {new Date(schedule.last_triggered_at).toLocaleString()}
          </span>
        )}
      </div>

      {schedule.last_message && (
        <p className="text-[11px] text-muted italic line-clamp-2">
          {schedule.last_message}
        </p>
      )}
    </div>
  );
}
