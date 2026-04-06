import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { setAccessToken } from "../api/client";

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const token = await login(username, password);
      setAccessToken(token);
      navigate("/");
    } catch {
      setError("Invalid username or password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <div className="bg-surface border border-border rounded-xl p-8 w-full max-w-sm">
        <h1 className="text-xl font-semibold text-fg mb-6 text-center">
          OPALX Regression Suite
        </h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm text-muted mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              autoFocus
              required
            />
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
              required
            />
          </div>
          {error && <p className="text-failed text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="bg-accent text-bg font-medium rounded-md py-2 text-sm hover:brightness-110 transition disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
