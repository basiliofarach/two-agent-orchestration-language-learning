import { CompositionRoot } from "~/.server/composition-root";
import { FixtureLog } from "~/.server/fixture-log";
import { RouteParams } from "~/.server/route-params";
import type { Route } from "./+types/_base.sessions.$sessionId_.events";

/** One session's SSE snapshot. The browser calls this route, not FastAPI. */
export async function loader({ request, params }: Route.LoaderArgs) {
  const sessionId = new RouteParams(params).uuid("sessionId", "Session");
  const body = await new CompositionRoot(process.env, FixtureLog.from(request))
    .dashboardSource()
    .events(sessionId, request.headers.get("Last-Event-ID"));
  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
