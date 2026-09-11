const BACKEND = process.env.AGENT_BACKEND_URL ?? "http://127.0.0.1:8000";

/** Lists what the agent can currently do, straight from the MCP server. */
export async function GET() {
  try {
    const upstream = await fetch(`${BACKEND}/tools`, { cache: "no-store" });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error), tools: [] },
      { status: 502 },
    );
  }
}
