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
