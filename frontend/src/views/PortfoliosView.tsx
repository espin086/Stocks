import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ResultPayload } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { ResultTable } from "@/components/ResultTable";

/** Portfolios saved by 0003: create, edit, delete — the CLI sees every change at once. */
export function PortfoliosView() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["portfolios"], queryFn: () => api.post<ResultPayload>("/api/v1/portfolio/list", {}) });
  const [name, setName] = useState("");
  const [tickers, setTickers] = useState("");
  const [weights, setWeights] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      api.post<{ message: string }>("/api/v1/portfolio/save", {
        name,
        tickers: tickers.split(/[\s,]+/).filter(Boolean),
        weights: weights.split(/[\s,]+/).filter(Boolean).map(Number),
        force: true,
      }),
    onSuccess: (r) => {
      setMessage(r.message);
      void qc.invalidateQueries({ queryKey: ["portfolios"] });
    },
    onError: (e) => setMessage((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (n: string) => api.post("/api/v1/portfolio/delete", { name: n, yes: true }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>portfolios</CardTitle>
        <ul className="space-y-1 text-sm">
          {(data?.rows ?? []).map((r) => (
            <li key={String(r.name)} className="flex items-center gap-3">
              <Link to={`/portfolios/${String(r.name)}`} className="text-accent">
                {String(r.name)}
              </Link>
              <span className="text-xs text-fg-muted">
                {String(r.holdings)} holdings{r.weighted ? ", weighted" : ""}
              </span>
              <Button
                variant="ghost"
                onClick={() => {
                  if (confirm(`Delete portfolio ${String(r.name)}?`)) remove.mutate(String(r.name));
                }}
              >
                delete
              </Button>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardTitle>save a portfolio</CardTitle>
        <div className="grid gap-2 md:grid-cols-3">
          <input aria-label="name" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} className="rounded border border-border bg-bg px-2 py-1 text-sm" />
          <input aria-label="tickers" placeholder="tickers, space separated" value={tickers} onChange={(e) => setTickers(e.target.value)} className="rounded border border-border bg-bg px-2 py-1 text-sm" />
          <input aria-label="weights" placeholder="weights (optional)" value={weights} onChange={(e) => setWeights(e.target.value)} className="rounded border border-border bg-bg px-2 py-1 text-sm" />
        </div>
        <div className="mt-2 flex items-center gap-2">
          <Button onClick={() => save.mutate()} disabled={!name || !tickers}>
            save
          </Button>
          {message && <span className="text-xs">{message}</span>}
        </div>
      </Card>
    </div>
  );
}

export function PortfolioView() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const { data, error } = useQuery({ queryKey: ["portfolio", name], queryFn: () => api.post<ResultPayload>("/api/v1/portfolio/show", { name }) });
  if (error) return <p className="text-fail">{(error as Error).message}</p>;
  if (!data) return <p>loading…</p>;
  return (
    <Card>
      <CardTitle>portfolio {name}</CardTitle>
      <div className="mb-2 flex gap-2">
        <Button variant="ghost" onClick={() => navigate("/commands/optimize.markowitz", { state: { params: { portfolio: name } } })}>
          optimize
        </Button>
        <Button variant="ghost" onClick={() => navigate("/commands/optimize.backtest", { state: { params: { portfolio: name } } })}>
          backtest
        </Button>
      </div>
      <ResultTable columns={data.columns ?? []} rows={data.rows ?? []} name={`portfolio-${name}`} />
    </Card>
  );
}
