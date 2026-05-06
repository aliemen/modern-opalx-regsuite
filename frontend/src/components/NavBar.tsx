import { type ComponentType, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Archive,
  BookOpen,
  CalendarClock,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Play,
  Settings,
  Sun,
  X,
} from "lucide-react";
import { getCurrentRun } from "../api/runs";
import { logout } from "../api/auth";
import { setAccessToken } from "../api/client";
import regsuiteIconUrl from "../assets/regsuite-icon.png";

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

const NAV_ITEMS: {
  to: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/activity", label: "Activity", icon: History },
  { to: "/catalog", label: "Catalog", icon: BookOpen },
  { to: "/trigger", label: "Run", icon: Play },
  { to: "/schedule", label: "Schedule", icon: CalendarClock },
  { to: "/archive", label: "Archive", icon: Archive },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function NavBar() {
  const navigate = useNavigate();
  const { dark, toggle } = useDarkMode();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { data: activeRun } = useQuery({
    queryKey: ["current-run"],
    queryFn: getCurrentRun,
    refetchInterval: 5000,
  });

  async function handleLogout() {
    await logout();
    setAccessToken(null);
    setDrawerOpen(false);
    navigate("/login");
  }

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setDrawerOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  const activeRunLink =
    activeRun && activeRun.status === "running" ? (
      <Link
        to="/live"
        onClick={() => setDrawerOpen(false)}
        className="flex items-center gap-1.5 text-accent text-sm animate-pulse"
      >
        <Activity size={15} />
        <span className="hidden sm:inline">Run in progress</span>
      </Link>
    ) : null;

  return (
    <nav className="bg-surface border-b border-border px-4 py-3 sm:px-6 flex items-center gap-4">
      <div className="flex items-center gap-6 min-w-0">
        <Link
          to="/"
          onClick={() => setDrawerOpen(false)}
          className="flex items-center gap-2 text-accent font-semibold text-lg tracking-tight min-w-0"
        >
          <img
            src={regsuiteIconUrl}
            alt=""
            className="w-7 h-7 shrink-0"
          />
          <span className="truncate">OPALX Reg Suite</span>
        </Link>

        <div className="hidden md:flex items-center gap-4">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors whitespace-nowrap"
            >
              <Icon size={15} />
              {label}
            </Link>
          ))}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2 md:gap-4 shrink-0">
        {activeRunLink}

        <button
          onClick={toggle}
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          className="flex items-center justify-center w-7 h-7 rounded-md text-muted hover:text-fg hover:bg-border/40 transition-colors"
        >
          {dark ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        <button
          onClick={handleLogout}
          className="hidden md:flex items-center gap-1.5 text-muted hover:text-fg text-sm transition-colors"
        >
          <LogOut size={15} />
          Logout
        </button>

        <button
          onClick={() => setDrawerOpen(true)}
          title="Open navigation"
          className="flex md:hidden items-center justify-center w-8 h-8 rounded-md text-muted hover:text-fg hover:bg-border/40 transition-colors"
        >
          <Menu size={18} />
        </button>
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute right-0 top-0 h-full w-72 max-w-[85vw] bg-surface border-l border-border shadow-xl p-4 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <span className="text-fg font-semibold">Navigation</span>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                className="flex items-center justify-center w-8 h-8 rounded-md text-muted hover:text-fg hover:bg-border/40 transition-colors"
                title="Close navigation"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex flex-col gap-1">
              {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  onClick={() => setDrawerOpen(false)}
                  className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-muted hover:text-fg hover:bg-border/30 transition-colors"
                >
                  <Icon size={16} />
                  {label}
                </Link>
              ))}
            </div>
            <button
              onClick={handleLogout}
              className="mt-auto flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-muted hover:text-fg hover:bg-border/30 transition-colors"
            >
              <LogOut size={16} />
              Logout
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
