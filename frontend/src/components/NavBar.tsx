import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, LogOut, Play, LayoutDashboard } from "lucide-react";
import { getCurrentRun } from "../api/runs";
import { logout } from "../api/auth";
import { setAccessToken } from "../api/client";

export function NavBar() {
  const navigate = useNavigate();
  const { data: activeRun } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: 5000,
  });

  async function handleLogout() {
    await logout();
    setAccessToken(null);
    navigate("/login");
  }

  return (
    <nav className="bg-surface border-b border-border px-6 py-3 flex items-center gap-6">
      <Link to="/" className="text-accent font-semibold text-lg tracking-tight">
        OPALX Reg Suite
      </Link>

      <div className="flex items-center gap-4 ml-4">
        <Link
          to="/"
          className="flex items-center gap-1.5 text-muted hover:text-white text-sm transition-colors"
        >
          <LayoutDashboard size={15} />
          Dashboard
        </Link>
        <Link
          to="/trigger"
          className="flex items-center gap-1.5 text-muted hover:text-white text-sm transition-colors"
        >
          <Play size={15} />
          Run
        </Link>
      </div>

      <div className="ml-auto flex items-center gap-4">
        {activeRun && activeRun.status === "running" && (
          <Link
            to="/live"
            className="flex items-center gap-1.5 text-accent text-sm animate-pulse"
          >
            <Activity size={15} />
            Run in progress
          </Link>
        )}
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 text-muted hover:text-white text-sm transition-colors"
        >
          <LogOut size={15} />
          Logout
        </button>
      </div>
    </nav>
  );
}
