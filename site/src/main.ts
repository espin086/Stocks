// The page is readable before this runs. This script fills in build-time facts,
// wires the copy buttons, then — after first paint — loads the animated figures.
import "./style.css";
import generated from "./generated.json";
import meta from "./data/figures-meta.json";
import backtest from "./data/backtest.json";
import terminal from "./data/terminal.txt?raw";

const $ = <T extends Element>(selector: string): T | null => document.querySelector<T>(selector);
const $$ = <T extends Element>(selector: string): T[] => Array.from(document.querySelectorAll<T>(selector));
export const reducedMotion = (): boolean => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---- build-time facts: version and install commands are generated, never typed here
for (const el of $$("[data-version]")) el.textContent = generated.version;
const pip = $("[data-install-pip]");
if (pip) pip.textContent = generated.install.pip;
const docker = $("[data-install-docker]");
if (docker) docker.textContent = generated.install.docker;

// ---- copy buttons announce their result to assistive tech via the status line
const status = $<HTMLElement>("#copy-status");
for (const button of $$<HTMLButtonElement>("button[data-copy]")) {
  button.addEventListener("click", async () => {
    const text = button.dataset.copy === "docker" ? generated.install.docker : generated.install.pip;
    try {
      await navigator.clipboard.writeText(text);
      if (status) status.textContent = `Copied: ${text}`;
    } catch {
      if (status) status.textContent = "Copy failed — select the command and copy it manually.";
    }
  });
}

// ---- figures' text alternatives and sources (present whether or not a chart renders)
const tickers = meta.tickers.join(" ");
const frontierSource = `${tickers}, ${meta.frontier_window[0]} to ${meta.frontier_window[1]}, ${meta.estimators.expected_return} returns, ${meta.estimators.covariance} covariance. Data: ${meta.data_source}.`;
const equitySource = `${tickers}, ${backtest.oos_start} to ${backtest.oos_end}, lookback ${meta.backtest.lookback}, ${meta.backtest.rebalance} rebalancing, ${backtest.cost_bps} bps a side, ${backtest.n_rebalances} rebalances. Data: ${meta.data_source}. Hypothetical.`;
const set = (selector: string, text: string) => {
  const el = $(selector);
  if (el) el.textContent = text;
};
set("[data-frontier-source]", frontierSource);
set("[data-equity-source]", equitySource);
set(
  "[data-equity-summary]",
  `Walk-forward Sharpe ${backtest.walk_forward_sharpe.toFixed(2)} against equal weight ${backtest.benchmark_sharpe.toFixed(2)}; max drawdown ${(backtest.max_drawdown * 100).toFixed(1)}%.`,
);
set("[data-sharpe-in-sample]", backtest.in_sample_sharpe.toFixed(2));
set("[data-sharpe-walk-forward]", backtest.walk_forward_sharpe.toFixed(2));
set(
  "[data-honesty-text]",
  `In-sample max-Sharpe (${backtest.in_sample_sharpe.toFixed(2)}) versus walk-forward (${backtest.walk_forward_sharpe.toFixed(2)}) on ${tickers}, ${backtest.oos_start} to ${backtest.oos_end}; ${backtest.cost_bps} bps costs charged, equal-weight benchmark ${backtest.benchmark_sharpe.toFixed(2)} on the same schedule. Hypothetical, computed by sobres.`,
);
set("[data-terminal-source]", `Recorded ${meta.recorded_at.slice(0, 10)} from: ${meta.commands.markowitz}. Data: ${meta.data_source}.`);
set(
  "[data-data-note]",
  meta.synthetic
    ? "Figures on this page were computed by sobres from the repository's recorded fixtures, which are synthesized random walks in each provider's payload shape — not market data. They demonstrate the tool, not any security."
    : "Figures on this page were computed by sobres from data recorded from the named providers.",
);
const term = $<HTMLElement>("#terminal");
const termText = $("[data-terminal-text]");
if (term) term.dataset.command = meta.commands.markowitz.replace(/^sobres /, "sobres ");
if (termText) termText.textContent = terminal; // final state first; the typing effect replays it

// ---- after first paint: charts and motion, both deferred and both optional
const start = () => {
  void import("./figures").then((m) => m.drawFigures());
  if (!reducedMotion()) void import("./motion").then((m) => m.animate(terminal));
};
const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback;
if (typeof idle === "function") {
  idle(start);
} else {
  window.addEventListener("load", () => setTimeout(start, 0));
}
