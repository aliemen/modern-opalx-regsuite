export const inputCls =
  "w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent";

export const textareaCls =
  "w-full resize-y bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm font-mono focus:outline-none focus:border-accent";

export const selectCls =
  "w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent";

export const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/;

export function validateId(id: string): string | null {
  const value = id.trim();
  if (!value) return "ID is required.";
  if (!idPattern.test(value)) {
    return "ID must start with a letter or number and use only letters, digits, '.', '_' or '-'.";
  }
  return null;
}

export function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function linesToArray(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function arrayToLines(values?: string[] | null): string {
  return (values ?? []).join("\n");
}

export function intFromString(
  value: string,
  label: string,
  min: number,
  allowBlank = false,
): { value: number | null; error: string | null } {
  const trimmed = value.trim();
  if (!trimmed) {
    return allowBlank
      ? { value: null, error: null }
      : { value: null, error: `${label} is required.` };
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < min) {
    return { value: null, error: `${label} must be an integer >= ${min}.` };
  }
  return { value: parsed, error: null };
}

export function deriveCmakeValue(args: string[] | null | undefined, key: string): string | null {
  const prefix = `-D${key}=`;
  const match = (args ?? []).find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : null;
}

export function generatedLabel(generated: boolean): string {
  return generated ? "generated" : "manual";
}

