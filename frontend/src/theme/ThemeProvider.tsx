import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePreference = "dark" | "light" | "system";
const KEY = "sobres.theme";

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: "dark" | "light";
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
  } catch {
    /* storage unavailable */
  }
  return "dark"; // dark by default
}

function resolve(preference: ThemePreference): "dark" | "light" {
  if (preference === "system") {
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return preference;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [resolved, setResolved] = useState<"dark" | "light">(() => resolve(readPreference()));

  useEffect(() => {
    const apply = () => {
      const next = resolve(preference);
      setResolved(next);
      document.documentElement.classList.toggle("dark", next === "dark");
    };
    apply();
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolved,
      setPreference: (p) => {
        try {
          localStorage.setItem(KEY, p);
        } catch {
          /* ignore */
        }
        setPreferenceState(p);
      },
    }),
    [preference, resolved],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}

/** Chart colours read the same tokens the rest of the UI uses. */
export interface ChartTokens {
  fg: string;
  muted: string;
  border: string;
  accent: string;
  bg: string;
  series: string;
}

export function tokens(): ChartTokens {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    fg: read("--fg"),
    muted: read("--fg-muted"),
    border: read("--border"),
    accent: read("--accent"),
    bg: read("--bg-elev"),
    series: [1, 2, 3, 4, 5, 6].map((i) => read(`--series-${i}`)).join(","),
  };
}

export function prefersReducedMotion(): boolean {
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}
