import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  toggleSchedule,
  updateSchedule,
  type Schedule,
  type ScheduleWriteBody,
} from "../api/schedules";

const SCHEDULES_KEY = ["schedules"];

export function useSchedulesQuery() {
  return useQuery<Schedule[]>({
    queryKey: SCHEDULES_KEY,
    queryFn: listSchedules,
    refetchInterval: 30_000,
  });
}

export function useScheduleMutations() {
  const qc = useQueryClient();

  const createMut = useMutation({
    mutationFn: (body: ScheduleWriteBody) => createSchedule(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: ScheduleWriteBody }) =>
      updateSchedule(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });

  const toggleMut = useMutation({
    mutationFn: (id: string) => toggleSchedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSchedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SCHEDULES_KEY }),
  });

  return { createMut, updateMut, toggleMut, deleteMut };
}
