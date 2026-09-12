import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { useTheme, type ThemePreference } from "@/theme/ThemeProvider";

interface Setting {
  key: string;
  env: string;
  description: string;
  type: string;
  secret: boolean;
  required: boolean;
  obtain: string | null;
  affects: string[];
  choices: string[];
  has_live_validator: boolean;
  value: string;
  source: string;
}

/** Generated from the settings registry; saving writes through `sobres config set`. */
export function SettingsView() {
  const qc = useQueryClient();
  const { preference, setPreference } = useTheme();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<{ settings: Setting[]; config_path: string }>("/api/v1/settings") });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (s: { key: string; value: string }) => api.put<{ message: string }>("/api/v1/settings", s),
    onSuccess: (r, vars) => {
      setNotes((n) => ({ ...n, [vars.key]: r.message }));
      setDrafts((d) => ({ ...d, [vars.key]: "" }));
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e, vars) => setNotes((n) => ({ ...n, [vars.key]: String((e as Error).message) })),
  });
  const verify = async (key: string) => {
    try {
      const r = await api.post<{ ok: boolean; message: string }>(`/api/v1/settings/${key}/verify`, { value: drafts[key] || null });
      setNotes((n) => ({ ...n, [key]: `${r.ok ? "verified" : "failed"}: ${r.message}` }));
    } catch (e) {
      setNotes((n) => ({ ...n, [key]: String((e as Error).message) }));
    }
  };
  if (!data) return <p>loading…</p>;
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>appearance</CardTitle>
        <div className="flex gap-2">
          {(["dark", "light", "system"] as ThemePreference[]).map((p) => (
            <Button key={p} variant={preference === p ? "primary" : "ghost"} onClick={() => setPreference(p)}>
              {p}
            </Button>
          ))}
        </div>
      </Card>
      <Card>
        <CardTitle>settings</CardTitle>
        <p className="mb-3 text-xs text-fg-muted">config file: {data.config_path}. Secrets are shown masked and never echoed back.</p>
        <div className="space-y-4">
          {data.settings.map((s) => (
            <div key={s.key} className="grid gap-1 md:grid-cols-[220px_1fr]">
              <div>
                <div className="text-sm font-medium">{s.key}</div>
                <div className="text-xs text-fg-muted">{s.env}</div>
              </div>
              <div>
                <p className="text-xs text-fg-muted">{s.description}</p>
                {s.obtain && (
                  <p className="text-xs">
                    obtain: {s.obtain.startsWith("http") ? <a className="text-accent underline" href={s.obtain} target="_blank" rel="noreferrer">{s.obtain}</a> : s.obtain}
                  </p>
                )}
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-fg-muted">
                    current: {s.value} ({s.source})
                  </span>
                  {s.choices.length ? (
                    <select value={drafts[s.key] ?? ""} onChange={(e) => setDrafts((d) => ({ ...d, [s.key]: e.target.value }))} className="rounded border border-border bg-bg px-2 py-1 text-sm">
                      <option value="">(keep)</option>
                      {s.choices.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input type={s.secret ? "password" : "text"} autoComplete="off" value={drafts[s.key] ?? ""} onChange={(e) => setDrafts((d) => ({ ...d, [s.key]: e.target.value }))} className="rounded border border-border bg-bg px-2 py-1 text-sm" aria-label={`new value for ${s.key}`} />
                  )}
                  <Button variant="ghost" disabled={!drafts[s.key]} onClick={() => save.mutate({ key: s.key, value: drafts[s.key] ?? "" })}>
                    save
                  </Button>
                  {s.has_live_validator && (
                    <Button variant="ghost" onClick={() => void verify(s.key)}>
                      verify
                    </Button>
                  )}
                </div>
                {notes[s.key] && <p className="mt-1 text-xs">{notes[s.key]}</p>}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
