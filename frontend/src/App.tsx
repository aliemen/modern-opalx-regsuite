import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { getAccessToken, setAccessToken } from "./api/client";
import { tryRefresh } from "./api/auth";
import { NavBar } from "./components/NavBar";
import { LoginPage } from "./pages/LoginPage";
import { PublicRunDetailPage } from "./pages/PublicRunDetailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { TriggerPage } from "./pages/TriggerPage";
import { LiveRunPage } from "./pages/LiveRunPage";
import { ActivityPage } from "./pages/ActivityPage";
import { ArchivePage } from "./pages/ArchivePage";
import { RunListPage } from "./pages/results/RunListPage";
import { RunDetailPage } from "./pages/results/RunDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SchedulePage } from "./pages/SchedulePage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

function AuthGuard() {
  const [checked, setChecked] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    async function check() {
      if (getAccessToken()) {
        setAuthed(true);
      } else {
        const token = await tryRefresh();
        if (token) {
          setAccessToken(token);
          setAuthed(true);
        }
      }
      setChecked(true);
    }
    check();
  }, []);

  if (!checked) return null;
  if (!authed) return <Navigate to="/login" replace />;
  return (
    <div className="flex flex-col min-h-screen">
      <NavBar />
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/public/runs/:branch/:arch/:runId"
            element={<PublicRunDetailPage />}
          />
          <Route element={<AuthGuard />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/archive" element={<ArchivePage />} />
            <Route path="/trigger" element={<TriggerPage />} />
            <Route path="/schedule" element={<SchedulePage />} />
            <Route path="/live/:runId?" element={<LiveRunPage />} />
            <Route path="/results/:branch/:arch" element={<RunListPage />} />
            <Route path="/results/:branch/:arch/:runId" element={<RunDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
