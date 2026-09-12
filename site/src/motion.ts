// Scroll-driven motion: only loaded when the visitor has not asked for reduced motion.
// Everything here replays a state the page already shows as text.
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import backtest from "./data/backtest.json";

gsap.registerPlugin(ScrollTrigger);

export function animate(transcript: string): void {
  const lenis = new Lenis({ duration: 1.0, smoothWheel: true });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);

  // Terminal: type the command, then reveal the recorded output line by line.
  const term = document.getElementById("terminal");
  const text = term?.querySelector("[data-terminal-text]");
  if (term && text) {
    const command = term.dataset.command ?? "";
    const lines = transcript.split("\n");
    ScrollTrigger.create({
      trigger: term,
      start: "top 75%",
      once: true,
      onEnter: () => {
        text.textContent = "";
        term.dataset.command = "";
        const cursor = document.createElement("span");
        cursor.className = "cursor";
        cursor.setAttribute("aria-hidden", "true");
        term.append(cursor);
        const typing = { i: 0 };
        gsap.to(typing, {
          i: command.length,
          duration: Math.min(2.2, command.length * 0.03),
          ease: "none",
          onUpdate: () => {
            term.dataset.command = command.slice(0, Math.round(typing.i));
          },
          onComplete: () => {
            const shown = { n: 0 };
            gsap.to(shown, {
              n: lines.length,
              duration: Math.min(3, lines.length * 0.08),
              ease: "none",
              onUpdate: () => {
                text.textContent = lines.slice(0, Math.round(shown.n)).join("\n");
              },
              onComplete: () => {
                text.textContent = transcript;
                cursor.remove();
              },
            });
          },
        });
      },
    });
  }

  // Honesty: the in-sample number falls to the walk-forward one.
  const wf = document.querySelector<HTMLElement>("[data-sharpe-walk-forward]");
  if (wf) {
    const value = { v: backtest.in_sample_sharpe };
    ScrollTrigger.create({
      trigger: wf,
      start: "top 80%",
      once: true,
      onEnter: () => {
        gsap.to(value, {
          v: backtest.walk_forward_sharpe,
          duration: 1.6,
          ease: "power2.out",
          onUpdate: () => {
            wf.textContent = value.v.toFixed(2);
          },
          onComplete: () => {
            wf.textContent = backtest.walk_forward_sharpe.toFixed(2);
          },
        });
      },
    });
  }

  // Capabilities: fade in as they arrive. Content is visible immediately if scrolled past fast.
  for (const card of Array.from(document.querySelectorAll<HTMLElement>(".cap"))) {
    gsap.from(card, {
      opacity: 0,
      y: 16,
      duration: 0.5,
      ease: "power2.out",
      scrollTrigger: { trigger: card, start: "top 90%", once: true },
      overwrite: "auto",
    });
  }
}
