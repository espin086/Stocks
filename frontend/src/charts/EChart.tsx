import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart, BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { prefersReducedMotion, tokens, useTheme } from "@/theme/ThemeProvider";

echarts.use([LineChart, ScatterChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);

/** Themed ECharts host; animation follows prefers-reduced-motion and never blocks interaction. */
export function EChart({ option, height = 320, ariaLabel }: { option: EChartsOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const t = tokens();
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: !prefersReducedMotion(),
      animationDuration: 600,
      color: t.series.split(","),
      backgroundColor: "transparent",
      textStyle: { color: t.fg },
      ...option,
      grid: { left: 48, right: 16, top: 32, bottom: 40, ...(option.grid as object) },
      xAxis: Array.isArray(option.xAxis) ? option.xAxis : { ...(option.xAxis as object), axisLine: { lineStyle: { color: t.border } }, axisLabel: { color: t.muted } },
      yAxis: Array.isArray(option.yAxis) ? option.yAxis : { ...(option.yAxis as object), axisLine: { lineStyle: { color: t.border } }, splitLine: { lineStyle: { color: t.border } }, axisLabel: { color: t.muted } },
      tooltip: { backgroundColor: t.bg, borderColor: t.border, textStyle: { color: t.fg }, ...(option.tooltip as object) },
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [option, resolved]);
  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ height }} className="w-full max-w-full" />;
}
