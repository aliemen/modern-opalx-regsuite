import { api } from "./client";

export async function login(username: string, password: string): Promise<string> {
  const res = await api.post<{ access_token: string }>("/api/auth/login", {
    username,
    password,
  });
  return res.data.access_token;
}

export async function logout(): Promise<void> {
  await api.post("/api/auth/logout");
}

export async function tryRefresh(): Promise<string | null> {
  try {
    const res = await api.post<{ access_token: string }>(
      "/api/auth/refresh-cookie",
      {},
      { withCredentials: true }
    );
    return res.data.access_token;
  } catch {
    return null;
  }
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await api.post("/api/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export interface UsernameChangeResult {
  old_username: string;
  new_username: string;
  run_index_entries_changed: number;
  run_meta_files_changed: number;
  user_dir_moved: boolean;
}

export async function changeUsername(
  currentPassword: string,
  newUsername: string,
  confirmUsername: string
): Promise<UsernameChangeResult> {
  const res = await api.post<UsernameChangeResult>("/api/auth/change-username", {
    current_password: currentPassword,
    new_username: newUsername,
    confirm_username: confirmUsername,
  });
  return res.data;
}
