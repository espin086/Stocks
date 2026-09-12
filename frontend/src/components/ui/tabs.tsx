import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export const Tabs = TabsPrimitive.Root;
export const TabsList = ({ children }: { children: ReactNode }) => (
  <TabsPrimitive.List className="mb-3 flex gap-1 border-b border-border">{children}</TabsPrimitive.List>
);
export const TabsTrigger = ({ value, children }: { value: string; children: ReactNode }) => (
  <TabsPrimitive.Trigger
    value={value}
    className="px-3 py-1.5 text-sm text-fg-muted data-[state=active]:border-b-2 data-[state=active]:border-accent data-[state=active]:text-fg"
  >
    {children}
  </TabsPrimitive.Trigger>
);
export const TabsContent = TabsPrimitive.Content;
