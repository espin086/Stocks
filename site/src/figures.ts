// ECharts figures drawn from the recorded data. Loaded after first paint.
import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import frontier from "./data/frontier.json";
import backtest from "./data/backtest.json";

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

type Row = Record<string, number | boolean>;

function tokens() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return { fg: read("--fg"), muted: read("--fg-muted"), border: read("--border"), accent: read("--accent"), warn: read("--warn"), bg: read("--bg-elev") };
}

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

export function frontierOption(reduced: boolean): EChartsOption {
  const t = tokens();
  const rows = frontier.rows as Row[];
  const curve = rows.map((r) => [Number(r.vol), Number(r.ret)]);
  const named = (key: string) => rows.filter((r) => r[key]).map((r) => [Number(r.vol), Number(r.ret)]);
  const tickers = frontier.columns.filter((c) => !["ret", "vol", "sharpe", "min_variance", "max_sharpe"].includes(c));
  return {
    animation: !reduced,
    animationDuration: 1800,
    animationEasing: "cubicOut",
    backgroundColor: "transparent",
    textStyle: { color: t.fg },
    grid: { left: 52, right: 20, top: 36, bottom: 44 },
    tooltip: {
      trigger: "item",
      backgroundColor: t.bg,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (p: unknown) => {
        const row = rows[(p as { dataIndex: number }).dataIndex];
        if (!row) return "";
        return tickers.map((k) => `${k} ${(Number(row[k]) * 100).toFixed(1)}%`).join("<br/>");
      },
    },
    xAxis: { type: "value", name: "volatility", nameLocation: "middle", nameGap: 28, axisLabel: { color: t.muted, formatter: pct }, axisLine: { lineStyle: { color: t.border } }, splitLine: { show: false } },
    yAxis: { type: "value", name: "return", axisLabel: { color: t.muted, formatter: pct }, axisLine: { lineStyle: { color: t.border } }, splitLine: { lineStyle: { color: t.border } } },
    series: [
      { type: "line", name: "frontier", data: curve, smooth: true, showSymbol: false, lineStyle: { color: t.accent, width: 3 } },
      { type: "scatter", name: "min variance", data: named("min_variance"), symbolSize: 12, symbol: "diamond", itemStyle: { color: t.fg }, label: { show: true, formatter: "min variance", position: "right", color: t.muted } },
      {
        type: "scatter",
        name: "max Sharpe",
        data: named("max_sharpe"),
        symbolSize: 16,
        symbol: "triangle",
        itemStyle: { color: t.warn },
        label: { show: true, formatter: "max Sharpe", position: "top", color: t.fg, fontWeight: "bold" },
        animationDelay: reduced ? 0 : 1800, // lands last
      },
    ],
  };
}

export function equityOption(reduced: boolean): EChartsOption {
  const t = tokens();
  return {
    animation: !reduced,
    animationDuration: 1500,
    backgroundColor: "transparent",
    textStyle: { color: t.fg },
    grid: { left: 52, right: 20, top: 24, bottom: 56 },
    legend: { bottom: 0, textStyle: { color: t.muted } },
    tooltip: { trigger: "axis", backgroundColor: t.bg, borderColor: t.border, textStyle: { color: t.fg } },
    xAxis: { type: "time", axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.border } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.border } } },
    series: [
      { type: "line", name: "walk-forward strategy", showSymbol: false, sampling: "lttb", data: Object.entries(backtest.equity_curve), lineStyle: { color: t.accent, width: 2 } },
      { type: "line", name: "equal weight", showSymbol: false, sampling: "lttb", data: Object.entries(backtest.benchmark_curve), lineStyle: { color: t.muted, type: "dashed" } },
    ],
  };
}

export function drawFigures(): void {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mount = (id: string, option: EChartsOption) => {
    const el = document.getElementById(id);
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    const render = () => chart.setOption(option);
    if (reduced || !("IntersectionObserver" in window)) {
      render();
    } else {
      // Draw when the figure enters the viewport: the animation is the explanation.
      const io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          render();
          io.disconnect();
        }
      }, { threshold: 0.3 });
      io.observe(el);
    }
    window.addEventListener("resize", () => chart.resize());
  };
  mount("frontier", frontierOption(reduced));
  mount("equity", equityOption(reduced));
}
