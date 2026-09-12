import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const base =
    "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-fg hover:opacity-90",
    ghost: "border border-border bg-transparent text-fg hover:bg-bg-elev",
    danger: "bg-fail text-white hover:opacity-90",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}
