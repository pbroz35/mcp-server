"use client";

import { HttpAgent } from "@ag-ui/client";
import { useCallback, useMemo, useRef, useState } from "react";

import type { ToolCall, Turn } from "./types";

/** Drives one AG-UI agent run and exposes the transcript as it streams.
 *
 *  Every callback mutates React state through a functional update, because
 *  events arrive faster than renders and a stale closure would drop them. */
export function useAgent() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadId = useRef(crypto.randomUUID());

  // Points at the Next.js proxy route, never at the backend directly, so the
  // backend URL and any credential stay server-side.
  const agent = useMemo(() => new HttpAgent({ url: "/api/agent" }), []);

  const patchAssistant = useCallback((fn: (turn: Turn) => Turn) => {
    setTurns((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].role === "assistant") {
          next[i] = fn(next[i]);
          return next;
        }
      }
      return next;
    });
  }, []);

  const patchTool = useCallback(
    (toolCallId: string, fn: (call: ToolCall) => ToolCall) => {
      patchAssistant((turn) => ({
        ...turn,
        toolCalls: turn.toolCalls.map((c) => (c.id === toolCallId ? fn(c) : c)),
      }));
    },
    [patchAssistant],
  );

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || running) return;
      setError(null);
      setRunning(true);

      const userTurn: Turn = {
        id: crypto.randomUUID(),
        role: "user",
        text,
        toolCalls: [],
        done: true,
      };
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: "",
        toolCalls: [],
        done: false,
      };
      setTurns((prev) => [...prev, userTurn, assistantTurn]);

      agent.messages = [
        ...agent.messages,
        { id: userTurn.id, role: "user", content: text },
      ];
      agent.threadId = threadId.current;

      try {
        await agent.runAgent(
          {},
          {
            onTextMessageContentEvent: ({ event }) => {
              patchAssistant((turn) => ({ ...turn, text: turn.text + event.delta }));
            },
            onToolCallStartEvent: ({ event }) => {
              patchAssistant((turn) => ({
                ...turn,
                toolCalls: [
                  ...turn.toolCalls,
                  {
                    id: event.toolCallId,
                    name: event.toolCallName,
                    args: "",
                    status: "running",
                    startedAt: Date.now(),
                  },
                ],
              }));
            },
            onToolCallArgsEvent: ({ event }) => {
              // Args stream as deltas, so they are appended rather than replaced.
              patchTool(event.toolCallId, (call) => ({
                ...call,
                args: call.args + event.delta,
              }));
            },
            onToolCallResultEvent: ({ event }) => {
              patchTool(event.toolCallId, (call) => ({
                ...call,
                result: typeof event.content === "string" ? event.content : JSON.stringify(event.content),
                status: "done",
                endedAt: Date.now(),
              }));
            },
            onRunErrorEvent: ({ event }) => {
              setError(event.message ?? "The run failed.");
            },
            onRunFinalized: () => {
              patchAssistant((turn) => ({
                ...turn,
                done: true,
                // Anything still running when the run ends never reported a
                // result; marking it done avoids a spinner that never stops.
                toolCalls: turn.toolCalls.map((c) =>
                  c.status === "running" ? { ...c, status: "done" as const } : c,
                ),
              }));
            },
          },
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        patchAssistant((turn) => ({ ...turn, done: true }));
      } finally {
        setRunning(false);
      }
    },
    [agent, patchAssistant, patchTool, running],
  );

  return { turns, running, error, send };
}
