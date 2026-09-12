import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { EChart } from "./EChart";

interface Backtest {
  equity_curve: Record<string, number>;
  benchmark_curve: Record<string, number>;
  weights_history: Record<string, Record<string, number>>;
}

function drawdown(curve: Record<string, number>): [string, number][] {
  let peak = -Infinity;
  return Object.entries(curve).map(([d, v]) => {
    peak = Math.max(peak, v);
    return [d, v / peak - 1];
  });
}

/** Equity curve with the benchmark overlaid, the drawdown series, and weights over time. */
export function BacktestCharts({ data }: { data: Backtest }) {
  const equity = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      xAxis: { type: "time" },
      yAxis: { type: "value", scale: true },
      dataZoom: [{ type: "inside" }],
      series: [
        { type: "line", name: "strategy", showSymbol: false, sampling: "lttb", large: true, data: Object.entries(data.equity_curve) },
        { type: "line", name: "equal weight", showSymbol: false, sampling: "lttb", large: true, data: Object.entries(data.benchmark_curve), lineStyle: { type: "dashed" } },
      ],
    }),
    [data],
  );
  const dd = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: "axis" },
      xAxis: { type: "time" },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      series: [{ type: "line", name: "drawdown", showSymbol: false, sampling: "lttb", large: true, areaStyle: {}, data: drawdown(data.equity_curve) }],
    }),
    [data],
  );
  const weights = useMemo<EChartsOption>(() => {
    const dates = Object.keys(data.weights_history);
    const assets = dates.length ? Object.keys(data.weights_history[dates[0] ?? ""] ?? {}) : [];
    return {
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", max: 1 },
      series: assets.map((a) => ({ type: "bar", stack: "w", name: a, data: dates.map((d) => data.weights_history[d]?.[a] ?? 0) })),
    };
  }, [data]);
  return (
    <div className="space-y-4">
      <EChart option={equity} ariaLabel="equity curve of the strategy and the equal-weight benchmark" />
      <EChart option={dd} height={200} ariaLabel="drawdown of the strategy over time" />
      <EChart option={weights} height={240} ariaLabel="portfolio weights at each rebalance" />
    </div>
  );
}
