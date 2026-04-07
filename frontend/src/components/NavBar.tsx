import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, LogOut, Moon, Play, Settings, Sun, LayoutDashboard } from "lucide-react";
import { getCurrentRun } from "../api/runs";
import { logout } from "../api/auth";
import { setAccessToken } from "../api/client";

function useDarkMode() {
  const [dark, setDark] = useState(
    () => document.documentElement.classList.contains("dark")
  );

  function toggle() {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("opalx-theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("opalx-theme", "light");
    }
  }

  return { dark, toggle };
}

export function NavBar() {
  const navigate = useNavigate();
  const { dark, toggle } = useDarkMode();

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
          className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <LayoutDashboard size={15} />
          Dashboard
        </Link>
        <Link
          to="/trigger"
          className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <Play size={15} />
          Run
        </Link>
        <Link
          to="/settings"
          className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <Settings size={15} />
          Settings
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

        {/* Light / dark toggle */}
        <button
          onClick={toggle}
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          className="flex items-center justify-center w-7 h-7 rounded-md text-muted hover:text-fg hover:bg-border/40 transition-colors"
        >
          {dark ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <LogOut size={15} />
          Logout
        </button>
      </div>
    </nav>
  );
}
