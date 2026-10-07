import { CompositionRoot } from "~/.server/composition-root";
import { RouteParams } from "~/.server/route-params";
import { SessionStatusBadge } from "~/components/session-status-badge";
import { ChainBreakNotice } from "~/components/turn/chain-break-notice";
import { UtcTime } from "~/components/utc-time";
import type { Route } from "./+types/route";
import { TurnSection } from "./turn-section";

export function meta({ loaderData }: Route.MetaArgs) {
  return [
    { title: loaderData ? `Session ${loaderData.sessionId}` : "Session" },
  ];
}

export async function loader({ params }: Route.LoaderArgs) {
  const sessionId = new RouteParams(params).uuid("sessionId", "Session");
  return new CompositionRoot().dashboardSource().session(sessionId);
}

export default function SessionRoute({ loaderData }: Route.ComponentProps) {
  const { chainBreak, turns } = loaderData;
  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-medium">Session</h1>
          <SessionStatusBadge open={loaderData.open} />
        </div>
        <p className="text-sm text-muted-foreground">
          Learner {loaderData.learnerId} · started{" "}
          <UtcTime iso={loaderData.startedAt} />
        </p>
      </header>
      {chainBreak ? <ChainBreakNotice chainBreak={chainBreak} /> : null}
      {turns.length === 0 && chainBreak === null ? (
        <p>This session has no turns.</p>
      ) : null}
      {turns.map((turn) => (
        <TurnSection key={turn.turnId} turn={turn} />
      ))}
    </div>
  );
}
