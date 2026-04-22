import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Lock, AlertTriangle, Check } from "lucide-react";
import { changePassword, logout } from "../../api/auth";
import { setAccessToken } from "../../api/client";

const MIN_PASSWORD_LENGTH = 12;

/**
 * Self-service password rotation.
 *
 * Flow: user submits current + new + confirm; backend verifies current,
 * re-hashes the new one, and clears the refresh cookie so any other session
 * for this user cannot silently refresh. On success we clear the in-memory
 * access token and bounce to /login.
 */
export function PasswordSection() {
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const mut = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
    onSuccess: async () => {
      setError(null);
      setDone(true);
      // Best-effort server-side logout; ignore failures so local cleanup still happens.
      try {
        await logout();
      } catch {
        // noop -- cookie is already cleared by change-password.
      }
      setAccessToken(null);
      // Short delay so the user can read the success banner before redirect.
      setTimeout(() => navigate("/login"), 1500);
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(
        typeof detail === "string" ? detail : "Failed to change password."
      );
    },
  });

  function clientSideValidate(): string | null {
    if (!currentPassword) return "Enter your current password.";
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      return `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    if (newPassword === currentPassword) {
      return "New password must differ from the current password.";
    }
    if (newPassword !== confirmPassword) {
      return "New password and confirmation do not match.";
    }
    return null;
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const problem = clientSideValidate();
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    mut.mutate();
  }

  const disabled = mut.isPending || done;

  return (
    <div className="bg-surface border border-border rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-fg text-lg font-medium flex items-center gap-2">
          <Lock size={18} />
          Password
        </h2>
      </div>
      <p className="text-muted text-sm mb-5">
        Change your sign-in password. After a successful change you will be
        signed out of this browser and any other session, and must log in again
        with the new password.
      </p>

      {error && (
        <div className="mb-4 flex items-start gap-2 text-failed text-sm bg-failed/10 border border-failed/40 rounded-md p-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {done && (
        <div className="mb-4 flex items-start gap-2 text-passed text-sm bg-passed/10 border border-passed/40 rounded-md p-3">
          <Check size={16} className="mt-0.5 shrink-0" />
          <span>Password changed. Redirecting to sign in…</span>
        </div>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-3 max-w-sm">
        <div>
          <label className="block text-sm text-muted mb-1">
            Current password
          </label>
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
          <label className="block text-sm text-muted mb-1">
            New password
            <span className="text-muted/70 ml-1 text-xs">
              (min. {MIN_PASSWORD_LENGTH} characters)
            </span>
          </label>
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            disabled={disabled}
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent disabled:opacity-50"
            required
            minLength={MIN_PASSWORD_LENGTH}
          />
        </div>
        <div>
          <label className="block text-sm text-muted mb-1">
            Confirm new password
          </label>
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
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
            {mut.isPending ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </div>
  );
}
