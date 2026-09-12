import { lazy, Suspense } from "react";
import type { CommandSchema, ResultPayload } from "@/api/client";
import { Disclaimer } from "@/components/Disclaimer";
import { ProvenanceBlock } from "@/components/Provenance";
import { ResultTable } from "@/components/ResultTable";
import { Link } from "react-router-dom";

const FrontierChart = lazy(() => import("@/charts/FrontierChart").then((m) => ({ default: m.FrontierChart })));
const BacktestCharts = lazy(() => import("@/charts/BacktestCharts").then((m) => ({ default: m.BacktestCharts })));

function headerLines(schema: CommandSchema, result: ResultPayload): string[] {
  const lines: string[] = [];
  if (schema.name === "optimize.markowitz") {
    const est = result.estimators as Record<string, unknown> | undefined;
    lines.push(`objective: ${String(result.objective)}`);
    if (est) lines.push(`estimators: ${String(est.expected_return)} expected returns, ${String(est.covariance)} covariance${est.shrinkage != null ? `, shrinkage ${Number(est.shrinkage).toFixed(3)}` : ""}`);
    lines.push(
      `expected return ${(Number(result.expected_return) * 100).toFixed(2)}%, volatility ${(Number(result.volatility) * 100).toFixed(2)}%, sharpe ${Number(result.sharpe).toFixed(2)} (risk-free ${(Number(result.risk_free) * 100).toFixed(2)}%)`,
    );
    for (const w of (result.warnings as string[] | undefined) ?? []) lines.push(`warning: ${w}`);
  }
  if (schema.name === "optimize.backtest") {
    lines.push(`out-of-sample window: ${String(result.oos_start)} → ${String(result.oos_end)}${result.shifted_start ? " (shifted to the first date with a full lookback)" : ""}`);
    lines.push(`rebalance ${String(result.rebalance)}, lookback ${String(result.lookback)} observations, ${String(result.n_rebalances)} rebalances`);
    lines.push(`transaction costs ${String(result.cost_bps)} bps: total turnover ${Number(result.total_turnover).toFixed(4)}, total cost ${(Number(result.total_cost) * 100).toFixed(2)}% of value`);
  }
  if (typeof result.message === "string") lines.push(result.message);
  return lines;
}

/** One renderer for every result: provenance, the right chart, always the table. */
export function ResultView({ schema, result }: { schema: CommandSchema; result: ResultPayload }) {
  const columns = result.columns ?? (result.rows?.[0] ? Object.keys(result.rows[0]) : []);
  const rows = result.rows ?? [];
  const tickers = columns.filter((c) => !["ret", "vol", "sharpe", "min_variance", "max_sharpe", "index"].includes(c));
  return (
    <div>
      <ProvenanceBlock provenance={result.provenance} extra={headerLines(schema, result)} />
      {schema.name === "optimize.markowitz" && (
        <p className="mb-2 text-xs">
          This optimum is in-sample. <Link className="text-accent underline" to={`/commands/optimize.backtest`}>Run the walk-forward backtest</Link> for the same inputs before trusting it.
        </p>
      )}
      <Suspense fallback={<p className="text-sm text-fg-muted">loading chart…</p>}>
        {schema.name === "optimize.frontier" && rows.length > 0 && <FrontierChart rows={rows} tickers={tickers} />}
        {schema.name === "optimize.backtest" && result.equity_curve != null && (
          <BacktestCharts data={result as unknown as { equity_curve: Record<string, number>; benchmark_curve: Record<string, number>; weights_history: Record<string, Record<string, number>> }} />
        )}
      </Suspense>
      {columns.length > 0 && <ResultTable columns={columns} rows={rows} name={schema.name} />}
      {result.run != null && typeof result.run === "object" && <pre className="overflow-x-auto rounded border border-border bg-bg p-2 text-xs">{JSON.stringify(result.run, null, 2)}</pre>}
      {schema.report && <Disclaimer />}
    </div>
  );
}
