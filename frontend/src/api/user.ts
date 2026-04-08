import { api } from "./client";

export interface CurrentUser {
  username: string;
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const res = await api.get<CurrentUser>("/api/auth/me");
  return res.data;
}
