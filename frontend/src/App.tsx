import { useEffect, useState } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/api/client";
import { TokenGate } from "@/components/TokenGate";
import { Disclaimer } from "@/components/Disclaimer";
import { ThemeProvider, useTheme } from "@/theme/ThemeProvider";
import { HomeView } from "@/views/HomeView";
import { CommandView } from "@/views/CommandView";
import { SettingsView } from "@/views/SettingsView";
import { DoctorView } from "@/views/DoctorView";
import { RunDiffView, RunView, RunsView } from "@/views/RunsView";
import { PortfolioView, PortfoliosView } from "@/views/PortfoliosView";
import { JobsView } from "@/views/JobsView";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Shell() {
  const { preference, setPreference } = useTheme();
  const [gate, setGate] = useState<"checking" | "open" | "locked">("checking");
  useEffect(() => {
    const onUnauthorized = () => setGate("locked");
    window.addEventListener("sobres:unauthorized", onUnauthorized);
    api
      .get<{ token_required: boolean }>("/api/v1/health")
      .then(async (h) => {
        if (!h.token_required) return setGate("open");
        try {
          await api.get("/api/v1/commands");
          setGate("open");
        } catch {
          setGate("locked");
        }
      })
      .catch(() => setGate("open"));
    return () => window.removeEventListener("sobres:unauthorized", onUnauthorized);
  }, []);
  if (gate === "checking") return <p className="p-6">connecting…</p>;
  if (gate === "locked") return <TokenGate onDone={() => setGate("open")} />;
  const nav = [
    ["/", "commands"],
    ["/portfolios", "portfolios"],
    ["/runs", "runs"],
    ["/jobs", "jobs"],
    ["/doctor", "doctor"],
    ["/settings", "settings"],
  ] as const;
  return (
    <div className="mx-auto min-h-full max-w-7xl px-4 py-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <Link to="/" className="text-lg font-semibold">
          sobres
        </Link>
        <nav className="flex flex-wrap gap-3 text-sm" aria-label="primary">
          {nav.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "text-accent" : "text-fg-muted hover:text-fg")}>
              {label}
            </NavLink>
          ))}
          <button className="text-fg-muted hover:text-fg" onClick={() => setPreference(preference === "dark" ? "light" : "dark")} aria-label="toggle theme">
            {preference === "dark" ? "☾" : "☀"}
          </button>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomeView />} />
          <Route path="/commands/:name" element={<CommandView />} />
          <Route path="/settings" element={<SettingsView />} />
          <Route path="/doctor" element={<DoctorView />} />
          <Route path="/runs" element={<RunsView />} />
          <Route path="/runs/:id" element={<RunView />} />
          <Route path="/runs/:a/diff/:b" element={<RunDiffView />} />
          <Route path="/portfolios" element={<PortfoliosView />} />
          <Route path="/portfolios/:name" element={<PortfolioView />} />
          <Route path="/jobs" element={<JobsView />} />
          <Route path="*" element={<p>no such view</p>} />
        </Routes>
      </main>
      <footer className="mt-8">
        <Disclaimer />
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
