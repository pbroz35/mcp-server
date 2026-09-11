import { NextRequest } from "next/server";

const BACKEND = process.env.AGENT_BACKEND_URL ?? "http://127.0.0.1:8000";

/** Proxies the AG-UI run to the backend, streaming the SSE response straight
 *  through. Keeping it server-side means the backend URL and any credential
 *  never reach the browser. */
export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(`${BACKEND}/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body,
    // Node buffers a streamed body without this.
    // @ts-expect-error duplex is required for streaming request bodies.
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      `event: RUN_ERROR\ndata: ${JSON.stringify({
        type: "RUN_ERROR",
        message: `Backend returned ${upstream.status}.`,
      })}\n\n`,
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    );
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
