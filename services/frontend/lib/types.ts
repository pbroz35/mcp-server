/** The shapes the UI renders, built up from the AG-UI event stream. */

export type ToolStatus = "running" | "done" | "error";

/** One tool invocation, assembled from TOOL_CALL_START/ARGS/RESULT events. */
export interface ToolCall {
  id: string;
  name: string;
  args: string;
  result?: string;
  status: ToolStatus;
  startedAt: number;
  endedAt?: number;
}

/** A turn in the transcript. Tool calls are attached to the assistant turn that
 *  made them, so the UI can show the work inline with the answer. */
export interface Turn {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls: ToolCall[];
  done: boolean;
}

/** Human-readable labels for the MCP tools, so the trace reads as intent
 *  rather than function names. */
export const TOOL_LABELS: Record<string, { label: string; kind: string }> = {
  search_documents: { label: "Searching the document corpus", kind: "vector db" },
  get_context: { label: "Expanding a passage", kind: "vector db" },
  list_documents: { label: "Listing the corpus", kind: "vector db" },
  web_search: { label: "Searching the web", kind: "web" },
};

export function describeTool(name: string): { label: string; kind: string } {
  return TOOL_LABELS[name] ?? { label: name, kind: "mcp" };
}
