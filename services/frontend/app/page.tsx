"use client";

import { useState } from "react";

import { Transcript } from "@/components/Transcript";
import { ToolPalette } from "@/components/ToolPalette";
import { useAgent } from "@/lib/useAgent";

const EXAMPLES = [
  "What documents do you have access to?",
  "Search my documents for revenue trends and cite the pages.",
  "What happened in AI chip markets this week?",
];

export default function Home() {
  const { turns, running, error, send } = useAgent();
  const [draft, setDraft] = useState("");

  const submit = (text: string) => {
    send(text);
    setDraft("");
  };

  return (
    <div className="flex h-screen">
      <main className="flex flex-1 flex-col">
        <header className="border-b border-[var(--border)] px-6 py-3">
          <h1 className="text-sm font-semibold">Research Agent</h1>
          <p className="text-xs text-[var(--muted)]">
            LangChain deep agent · tools over MCP · streaming AG-UI events
          </p>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {turns.length === 0 ? (
            <div className="mx-auto max-w-2xl pt-16">
              <p className="mb-4 text-sm text-[var(--muted)]">Try asking:</p>
              <div className="space-y-2">
                {EXAMPLES.map((e) => (
                  <button
                    key={e}
                    onClick={() => submit(e)}
                    className="block w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-4 py-3 text-left text-sm hover:border-[var(--accent)]"
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-2xl">
              <Transcript turns={turns} />
            </div>
          )}

          {error && (
            <div className="mx-auto mt-4 max-w-2xl rounded border border-red-900/50 bg-red-950/30 p-3 text-sm text-red-300">
              {error}
            </div>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(draft);
          }}
          className="border-t border-[var(--border)] px-6 py-4"
        >
          <div className="mx-auto flex max-w-2xl gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask a research question…"
              disabled={running}
              className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel)] px-4 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={running || !draft.trim()}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-black disabled:opacity-40"
            >
              {running ? "Running…" : "Send"}
            </button>
          </div>
        </form>
      </main>

      <ToolPalette />
    </div>
  );
}
