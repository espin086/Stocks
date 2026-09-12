import { useState, type FormEvent } from "react";
import { api } from "@/api/client";
import { Button } from "./ui/button";

/** One-time paste of the deployment token; the server sets an httpOnly cookie. */
export function TokenGate({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/v1/auth/login", { token });
      onDone();
    } catch {
      setError("that token was not accepted");
    }
  };
  return (
    <form onSubmit={submit} className="mx-auto mt-24 max-w-md rounded-lg border border-border bg-bg-elev p-6">
      <h1 className="mb-2 text-lg font-semibold">Deployment token</h1>
      <p className="mb-4 text-sm text-fg-muted">
        This server is reachable beyond loopback, so it asks for the token <code>sobres serve</code> printed. It is stored
        as an httpOnly cookie and never placed in a URL.
      </p>
      <input
        type="password"
        autoComplete="off"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="mb-3 w-full rounded border border-border bg-bg px-2 py-1.5"
        aria-label="deployment token"
      />
      {error && <p className="mb-2 text-sm text-fail">{error}</p>}
      <Button type="submit">Continue</Button>
    </form>
  );
}
