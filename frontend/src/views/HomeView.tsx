import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type CommandSchema } from "@/api/client";
import { Card, CardTitle } from "@/components/ui/card";

export function useCommands() {
  return useQuery({
    queryKey: ["commands"],
    queryFn: () => api.get<{ commands: CommandSchema[] }>("/api/v1/commands").then((r) => r.commands),
    staleTime: Infinity,
  });
}

/** Every CLI capability, grouped exactly as the CLI groups them. */
export function HomeView() {
  const { data, isLoading, error } = useCommands();
  if (isLoading) return <p>loading the registry…</p>;
  if (error || !data) return <p className="text-fail">could not load the command registry</p>;
  const groups = new Map<string, CommandSchema[]>();
  for (const c of data) {
    const key = c.group ?? "root";
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {[...groups.entries()].map(([group, cmds]) => (
        <Card key={group}>
          <CardTitle>{group}</CardTitle>
          <ul className="space-y-1">
            {cmds.map((c) => (
              <li key={c.name}>
                <Link to={`/commands/${c.name}`} className="text-accent hover:underline">
                  {c.name}
                </Link>
                <span className="ml-2 text-xs text-fg-muted">{c.help}</span>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
