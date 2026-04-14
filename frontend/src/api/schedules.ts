import { api } from "./client";

export type DayOfWeek = "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN";

export const DAYS_ORDERED: DayOfWeek[] = [
  "MON",
  "TUE",
  "WED",
  "THU",
  "FRI",
  "SAT",
  "SUN",
];

export const DAY_LABEL: Record<DayOfWeek, string> = {
  MON: "Mon",
  TUE: "Tue",
  WED: "Wed",
  THU: "Thu",
  FRI: "Fri",
  SAT: "Sat",
  SUN: "Sun",
};

export interface ScheduleSpec {
  days: DayOfWeek[];
  time: string; // "HH:MM" 24h, server-local
}

export interface Schedule {
  id: string;
  name: string;
  enabled: boolean;
  spec: ScheduleSpec;
  branch: string;
  arch: string;
  regtests_branch?: string | null;
  connection_name: string;
  skip_unit: boolean;
  skip_regression: boolean;
  public: boolean;
  owner: string;
  created_at: string;
  modified_at: string;
  last_triggered_at?: string | null;
  last_run_id?: string | null;
  last_status?: string | null;
  last_message?: string | null;
}

export interface ScheduleWriteBody {
  name: string;
  enabled: boolean;
  spec: ScheduleSpec;
  branch: string;
  arch: string;
  regtests_branch?: string | null;
  connection_name: string;
  skip_unit: boolean;
  skip_regression: boolean;
  public: boolean;
}

export async function listSchedules(): Promise<Schedule[]> {
  const res = await api.get<Schedule[]>("/api/schedules");
  return res.data;
}

export async function createSchedule(body: ScheduleWriteBody): Promise<Schedule> {
  const res = await api.post<Schedule>("/api/schedules", body);
  return res.data;
}

export async function updateSchedule(
  id: string,
  body: ScheduleWriteBody,
): Promise<Schedule> {
  const res = await api.put<Schedule>(
    `/api/schedules/${encodeURIComponent(id)}`,
    body,
  );
  return res.data;
}

export async function toggleSchedule(id: string): Promise<Schedule> {
  const res = await api.post<Schedule>(
    `/api/schedules/${encodeURIComponent(id)}/toggle`,
  );
  return res.data;
}

export async function deleteSchedule(id: string): Promise<void> {
  await api.delete(`/api/schedules/${encodeURIComponent(id)}`);
}
