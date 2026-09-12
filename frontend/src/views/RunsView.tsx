import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type ResultPayload } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { ResultTable } from "@/components/ResultTable";

const NOTE = "stored runs record what was computed at the time; upstream data may have been revised since";

export function RunsView() {
  const { data } = useQuery({ queryKey: ["runs"], queryFn: () => api.post<ResultPayload>("/api/v1/run/list", { limit: 100 }) });
  const [selected, setSelected] = useState<string[]>([]);
  const navigate = useNavigate();
  const rows: Record<string, unknown>[] = data?.rows ?? [];
  return (
    <Card>
      <CardTitle>run history</CardTitle>
      <p className="mb-2 text-xs text-fg-muted">{NOTE}</p>
      <div className="mb-2 flex gap-2">
        <Button variant="ghost" disabled={selected.length !== 2} onClick={() => navigate(`/runs/${selected[0]}/diff/${selected[1]}`)}>
          compare selected
        </Button>
      </div>
      <ul className="space-y-1 text-sm">
        {rows.map((r) => (
          <li key={String(r.id)} className="flex items-center gap-2">
            <input
              type="checkbox"
              aria-label={`select run ${String(r.id)}`}
              checked={selected.includes(String(r.id))}
              onChange={(e) => setSelected((s) => (e.target.checked ? [...s, String(r.id)].slice(-2) : s.filter((x) => x !== String(r.id))))}
            />
            <Link to={`/runs/${String(r.id)}`} className="font-mono text-accent">
              {String(r.id)}
            </Link>
            <span>{String(r.command)}</span>
            <span className="text-xs text-fg-muted">{String(r.created_at)}</span>
            <span className="text-xs">{String(r.summary)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface RunRecord {
  id: string;
  command: string;
  created_at: string | null;
  summary: string;
  params: Record<string, unknown>;
  estimators: Record<string, unknown>;
  window: Record<string, unknown>;
  result: ResultPayload;
}

export function RunView() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["run", id], queryFn: () => api.post<{ run: RunRecord }>("/api/v1/run/show", { id }) });
  if (!data) return <p>loading…</p>;
  const run = data.run;
  const columns = run.result.columns ?? [];
  return (
    <Card>
      <CardTitle>
        run {run.id} — {run.command}
      </CardTitle>
      <p className="mb-2 text-xs text-fg-muted">{NOTE}</p>
      <p className="text-sm">{run.summary}</p>
      <div className="my-2 flex gap-2">
        <Button variant="ghost" onClick={() => navigate(`/commands/${run.command}`, { state: { params: run.params } })}>
          re-run with these parameters
        </Button>
      </div>
      <pre className="mb-3 overflow-x-auto rounded border border-border bg-bg p-2 text-xs">{JSON.stringify({ params: run.params, estimators: run.estimators, window: run.window }, null, 2)}</pre>
      {columns.length > 0 && <ResultTable columns={columns} rows={run.result.rows ?? []} name={`run-${run.id}`} />}
    </Card>
  );
}

export function RunDiffView() {
  const { a = "", b = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["diff", a, b], queryFn: () => api.post<ResultPayload>("/api/v1/run/diff", { a, b }) });
  if (error) return <p className="text-fail">{(error as Error).message}</p>;
  if (!data) return <p>loading…</p>;
  return (
    <Card>
      <CardTitle>
        {a} vs {b}
      </CardTitle>
      <ResultTable columns={data.columns ?? []} rows={data.rows ?? []} name="diff" />
    </Card>
  );
}
