import { DAYS_ORDERED, DAY_LABEL, type DayOfWeek } from "../../api/schedules";

interface DayPickerProps {
  value: DayOfWeek[];
  onChange: (next: DayOfWeek[]) => void;
  disabled?: boolean;
}

export function DayPicker({ value, onChange, disabled }: DayPickerProps) {
  function toggle(day: DayOfWeek) {
    if (disabled) return;
    const set = new Set(value);
    if (set.has(day)) set.delete(day);
    else set.add(day);
    // Keep the canonical Mon..Sun order.
    onChange(DAYS_ORDERED.filter((d) => set.has(d)));
  }

  return (
    <div className="flex gap-1.5 flex-wrap">
      {DAYS_ORDERED.map((day) => {
        const selected = value.includes(day);
        return (
          <button
            type="button"
            key={day}
            onClick={() => toggle(day)}
            disabled={disabled}
            className={
              "px-3 py-1.5 rounded-md text-xs border transition " +
              (selected
                ? "bg-accent text-bg border-accent"
                : "bg-bg text-muted border-border hover:text-fg")
            }
          >
            {DAY_LABEL[day]}
          </button>
        );
      })}
    </div>
  );
}
