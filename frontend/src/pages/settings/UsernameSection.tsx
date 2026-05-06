import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Check, UserRound } from "lucide-react";
import { changeUsername, logout, type UsernameChangeResult } from "../../api/auth";
import { setAccessToken } from "../../api/client";
import { getCurrentUser } from "../../api/user";

const USERNAME_RE = /^[A-Za-z0-9_.-]{3,64}$/;

export function UsernameSection() {
  const navigate = useNavigate();
  const { data: me } = useQuery({
    queryKey: ["auth-me"],
    queryFn: getCurrentUser,
  });

  const [currentPassword, setCurrentPassword] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [confirmUsername, setConfirmUsername] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<UsernameChangeResult | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      changeUsername(currentPassword, newUsername.trim(), confirmUsername.trim()),
    onSuccess: async (result) => {
      setError(null);
      setDone(result);
      try {
        await logout();
      } catch {
        // The backend already cleared the refresh cookie on success.
      }
      setAccessToken(null);
      setTimeout(() => navigate("/login"), 1800);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to change username.");
      setDone(null);
    },
  });

  function validate(): string | null {
    const next = newUsername.trim();
    const confirm = confirmUsername.trim();
    if (!currentPassword) return "Enter your current password.";
    if (!USERNAME_RE.test(next)) {
      return "Username must be 3-64 characters: letters, numbers, underscores, dots, and hyphens only.";
    }
    if (next === me?.username) {
      return "New username must differ from the current username.";
    }
    if (next !== confirm) {
      return "Username confirmation does not match.";
    }
    return null;
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    mut.mutate();
  }

  const disabled = mut.isPending || done !== null;

  return (
    <div className="bg-surface border border-border rounded-xl p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <UserRound size={18} />
          Username
        </h2>
      </div>

      <div className="mb-4 text-sm">
        <span className="text-muted">Current username</span>
        <span className="ml-2 font-mono text-fg">{me?.username ?? "..."}</span>
      </div>

      <div className="mb-5 flex items-start gap-2 rounded-md border border-failed/40 bg-failed/10 p-3 text-sm text-failed">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        <span>
          Only change this if absolutely necessary. The server rewrites historical
          run metadata across the complete data directory. Rename is blocked while
          you have active runs, queued runs, or any owned schedules.
        </span>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 text-failed text-sm bg-failed/10 border border-failed/40 rounded-md p-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {done && (
        <div className="mb-4 flex items-start gap-2 text-passed text-sm bg-passed/10 border border-passed/40 rounded-md p-3">
          <Check size={16} className="mt-0.5 shrink-0" />
          <span>
            Renamed to <span className="font-mono">{done.new_username}</span>.
            Updated {done.run_index_entries_changed} index{" "}
            {done.run_index_entries_changed === 1 ? "entry" : "entries"} and{" "}
            {done.run_meta_files_changed} run-meta file
            {done.run_meta_files_changed === 1 ? "" : "s"}. Redirecting to sign in.
          </span>
        </div>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-3 max-w-sm">
        <div>
          <label className="block text-sm text-muted mb-1">Current password</label>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            disabled={disabled}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent disabled:opacity-50"
            required
          />
        </div>
        <div>
          <label className="block text-sm text-muted mb-1">New username</label>
          <input
            type="text"
            autoComplete="username"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            disabled={disabled}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent disabled:opacity-50"
            required
          />
          <p className="text-muted text-xs mt-1">
            3-64 characters. Letters, numbers, underscores, dots, and hyphens.
          </p>
        </div>
        <div>
          <label className="block text-sm text-muted mb-1">Confirm username</label>
          <input
            type="text"
            value={confirmUsername}
            onChange={(e) => setConfirmUsername(e.target.value)}
            disabled={disabled}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent disabled:opacity-50"
            required
          />
        </div>
        <div>
          <button
            type="submit"
            disabled={disabled}
            className="bg-accent text-bg font-medium rounded-md px-4 py-2 text-sm hover:brightness-110 transition disabled:opacity-50"
          >
            {mut.isPending ? "Renaming..." : "Change username"}
          </button>
        </div>
      </form>
    </div>
  );
}
