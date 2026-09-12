import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

interface Check {
  name: string;
  category: string;
  status: "ok" | "warn" | "fail" | "skip";
  message: string;
  fix_hint: string | null;
  fixed?: string | null;
}
interface Report {
  checks: Check[];
  summary: Record<string, number>;
  exit_code: number;
}

const GLYPH: Record<Check["status"], string> = { ok: "✔", warn: "!", fail: "✘", skip: "-" };
const COLOR: Record<Check["status"], string> = { ok: "text-ok", warn: "text-warn", fail: "text-fail", skip: "text-fg-muted" };

/** `sobres doctor`'s checks, statuses, messages and next steps, from the same registry. */
export function DoctorView() {
  const [offline, setOffline] = useState(true);
  const run = useMutation({ mutationFn: (fix: boolean) => api.post<Report>("/api/v1/doctor", { offline, fix }) });
  const report = run.data;
  const groups = new Map<string, Check[]>();
  for (const c of report?.checks ?? []) groups.set(c.category, [...(groups.get(c.category) ?? []), c]);
  return (
    <Card>
      <CardTitle>doctor</CardTitle>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => run.mutate(false)} disabled={run.isPending}>
          run checks
        </Button>
        <Button variant="ghost" onClick={() => run.mutate(true)} disabled={run.isPending}>
          apply safe fixes
        </Button>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={offline} onChange={(e) => setOffline(e.target.checked)} /> offline (skip network checks)
        </label>
      </div>
      {report && (
        <div className="space-y-3">
          {[...groups.entries()].map(([category, checks]) => (
            <div key={category}>
              <h3 className="text-sm font-semibold">{category}</h3>
              <ul className="text-sm">
                {checks.map((c) => (
                  <li key={c.name} className="py-0.5">
                    <span className={`mr-2 font-mono ${COLOR[c.status]}`}>{GLYPH[c.status]}</span>
                    <span className="font-medium">{c.name}</span>: {c.message}
                    {c.fixed && <span className="text-ok"> (fixed: {c.fixed})</span>}
                    {c.fix_hint && (c.status === "warn" || c.status === "fail") && <div className="ml-6 text-xs text-fg-muted">→ {c.fix_hint}</div>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-sm text-fg-muted">
            {report.summary.ok} ok, {report.summary.warn} warnings, {report.summary.fail} failed, {report.summary.skip} skipped
          </p>
        </div>
      )}
    </Card>
  );
}
