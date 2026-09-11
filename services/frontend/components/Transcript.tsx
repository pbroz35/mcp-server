"use client";

import type { Turn } from "@/lib/types";

import { ToolCallCard } from "./ToolCallCard";

export function Transcript({ turns }: { turns: Turn[] }) {
  return (
    <div className="space-y-6">
      {turns.map((turn) =>
        turn.role === "user" ? (
          <div key={turn.id} className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl bg-[var(--accent)] px-4 py-2 text-black">
              {turn.text}
            </div>
          </div>
        ) : (
          <div key={turn.id} className="space-y-3">
            {turn.toolCalls.length > 0 && (
              <div className="space-y-2">
                {turn.toolCalls.map((call) => (
                  <ToolCallCard key={call.id} call={call} />
                ))}
              </div>
            )}
            {turn.text && (
              <div className="whitespace-pre-wrap leading-relaxed">{turn.text}</div>
            )}
            {!turn.done && turn.text === "" && turn.toolCalls.length === 0 && (
              <div className="text-sm text-[var(--muted)]">Thinking…</div>
            )}
          </div>
        ),
      )}
    </div>
  );
}
