"use client";

import { useState } from "react";

import { describeTool, type ToolCall } from "@/lib/types";

/** One tool invocation: what the agent is calling, with what, and what came back. */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const { label, kind } = describeTool(call.name);
  const elapsed = call.endedAt ? ((call.endedAt - call.startedAt) / 1000).toFixed(1) : null;

  let args: unknown = call.args;
  try {
    args = JSON.parse(call.args);
  } catch {
    // Args stream in as deltas, so mid-flight they are not yet valid JSON.
  }

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] text-sm">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left"
      >
        <span
          className={
            call.status === "running"
              ? "size-2 shrink-0 animate-pulse rounded-full bg-[var(--accent)]"
              : "size-2 shrink-0 rounded-full bg-emerald-500"
          }
          aria-hidden
        />
        <span className="font-medium">{label}</span>
        <span className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-[11px] text-[var(--muted)]">
          {kind}
        </span>
        <span className="ml-auto font-mono text-xs text-[var(--muted)]">
          {call.status === "running" ? "running…" : elapsed ? `${elapsed}s` : "done"}
        </span>
        <span className="text-[var(--muted)]">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-[var(--border)] px-3 py-2">
          <div>
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wide text-[var(--muted)]">
              {call.name} — arguments
            </div>
            <pre className="overflow-x-auto rounded bg-black/40 p-2 font-mono text-xs">
              {JSON.stringify(args, null, 2)}
            </pre>
          </div>
          {call.result !== undefined && (
            <div>
              <div className="mb-1 font-mono text-[11px] uppercase tracking-wide text-[var(--muted)]">
                result
              </div>
              <pre className="max-h-64 overflow-auto rounded bg-black/40 p-2 font-mono text-xs whitespace-pre-wrap">
                {call.result.slice(0, 4000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
