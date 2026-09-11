"use client";

import { useEffect, useState } from "react";

import { describeTool } from "@/lib/types";

interface Tool {
  name: string;
  description: string;
}

/** What the agent can currently do, fetched from the MCP server at load.
 *  Makes the point visible: the tool list is discovered, not hard-coded. */
export function ToolPalette() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/tools")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setTools(d.tools ?? [])))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <aside className="w-72 shrink-0 border-l border-[var(--border)] p-4">
      <h2 className="mb-1 text-sm font-semibold">Tools from MCP</h2>
      <p className="mb-3 text-xs text-[var(--muted)]">
        Discovered at runtime from the MCP server. The agent implements none of them itself.
      </p>

      {error && (
        <p className="rounded border border-amber-900/50 bg-amber-950/30 p-2 text-xs text-amber-300">
          Could not reach the MCP server: {error}
        </p>
      )}

      <ul className="space-y-2">
        {tools.map((t) => (
          <li key={t.name} className="rounded border border-[var(--border)] bg-[var(--panel)] p-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs">{t.name}</span>
              <span className="ml-auto rounded bg-black/30 px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted)]">
                {describeTool(t.name).kind}
              </span>
            </div>
            <p className="mt-1 text-xs leading-snug text-[var(--muted)]">
              {(t.description ?? "").split("\n")[0]}
            </p>
          </li>
        ))}
      </ul>

      {!error && tools.length === 0 && (
        <p className="text-xs text-[var(--muted)]">Loading…</p>
      )}
    </aside>
  );
}
