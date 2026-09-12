import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { EChart } from "./EChart";

type Row = Record<string, unknown>;

/** Risk/return scatter with the curve; hovering a point shows that portfolio's weights. */
export function FrontierChart({ rows, tickers }: { rows: Row[]; tickers: string[] }) {
  const [selected, setSelected] = useState<Row | null>(null);
  const option = useMemo<EChartsOption>(() => {
    const curve = rows.map((r) => [Number(r.vol), Number(r.ret)]);
    const named = (key: string) => rows.filter((r) => r[key]).map((r) => [Number(r.vol), Number(r.ret)]);
    return {
      tooltip: {
        trigger: "item",
        formatter: (p: unknown) => {
          const idx = (p as { dataIndex: number }).dataIndex;
          const row = rows[idx];
          if (!row) return "";
          setSelected(row);
          return tickers.map((t) => `${t}: ${(Number(row[t]) * 100).toFixed(1)}%`).join("<br/>");
        },
      },
      xAxis: { type: "value", name: "volatility", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      yAxis: { type: "value", name: "return", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      series: [
        { type: "line", name: "frontier", data: curve, smooth: true, symbolSize: 6, animationDuration: 900 },
        { type: "scatter", name: "min variance", data: named("min_variance"), symbolSize: 14, symbol: "diamond" },
        { type: "scatter", name: "max Sharpe", data: named("max_sharpe"), symbolSize: 14, symbol: "triangle" },
      ],
      legend: { bottom: 0 },
    };
  }, [rows, tickers]);
  return (
    <div>
      <EChart option={option} ariaLabel="efficient frontier: volatility against expected return; a table of the same rows follows" />
      {selected && (
        <p className="mt-1 text-xs text-fg-muted">
          hovered: ret {(Number(selected.ret) * 100).toFixed(2)}%, vol {(Number(selected.vol) * 100).toFixed(2)}% —{" "}
          {tickers.map((t) => `${t} ${(Number(selected[t]) * 100).toFixed(1)}%`).join(", ")}
        </p>
      )}
    </div>
  );
}
