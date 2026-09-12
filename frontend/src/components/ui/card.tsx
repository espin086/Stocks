import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-lg border border-border bg-bg-elev p-4 ${className}`} {...props} />;
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-2 text-base font-semibold">{children}</h2>;
}
