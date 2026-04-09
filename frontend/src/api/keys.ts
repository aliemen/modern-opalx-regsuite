import { api } from "./client";

export interface SshKeyInfo {
  name: string;
  created_at: string;
  fingerprint: string | null;
}

export async function listSshKeys(): Promise<SshKeyInfo[]> {
  const res = await api.get<SshKeyInfo[]>("/api/settings/ssh-keys");
  return res.data;
}

export async function uploadSshKey(
  name: string,
  file: File,
  cert?: File
): Promise<SshKeyInfo> {
  const form = new FormData();
  form.append("name", name);
  form.append("key_file", file);
  if (cert) form.append("cert_file", cert);
  const res = await api.post<SshKeyInfo>("/api/settings/ssh-keys", form);
  return res.data;
}

/**
 * Replace the contents of an existing key in place. Connections that
 * reference this key by name pick up the new contents on next use, so this
 * avoids the unlink → delete → re-add → re-link dance for short-lived keys
 * (e.g. CSCS Daint, where keys are valid for only one day).
 *
 * Passing `cert` replaces `<name>-cert.pub` too. Omit it to leave the
 * existing certificate untouched.
 */
export async function replaceSshKey(
  name: string,
  file: File,
  cert?: File
): Promise<SshKeyInfo> {
  const form = new FormData();
  form.append("key_file", file);
  if (cert) form.append("cert_file", cert);
  const res = await api.put<SshKeyInfo>(
    `/api/settings/ssh-keys/${encodeURIComponent(name)}`,
    form
  );
  return res.data;
}

export async function deleteSshKey(name: string): Promise<void> {
  await api.delete(`/api/settings/ssh-keys/${encodeURIComponent(name)}`);
}
