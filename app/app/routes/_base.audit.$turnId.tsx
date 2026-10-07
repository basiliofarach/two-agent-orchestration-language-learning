import { Link } from "react-router";

import { CompositionRoot } from "~/.server/composition-root";
import { RouteParams } from "~/.server/route-params";
import { GateTimeline } from "~/components/turn/gate-timeline";
import { TurnStatusBadge } from "~/components/turn/turn-status-badge";
import { Badge } from "~/components/ui/badge";
import type { Route } from "./+types/_base.audit.$turnId";

export function meta({ loaderData }: Route.MetaArgs) {
  return [{ title: loaderData ? `Audit ${loaderData.turn.turnId}` : "Audit" }];
}

export async function loader({ params }: Route.LoaderArgs) {
  const turnId = new RouteParams(params).uuid("turnId", "Turn");
  return new CompositionRoot().dashboardSource().auditTurn(turnId);
}

export default function AuditRoute({ loaderData }: Route.ComponentProps) {
  const { turn, recordIntact } = loaderData;
  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-medium">Audit record</h1>
        <p className="flex flex-wrap items-center gap-2">
          Turn {turn.turnIndex + 1}
          <TurnStatusBadge label={turn.statusLabel} />
          <Badge variant={recordIntact ? "secondary" : "destructive"}>
            {recordIntact ? "Record digest intact" : "Record digest broken"}
          </Badge>
        </p>
        <p>
          <Link to={`/sessions/${turn.sessionId}`} className="underline">
            Back to session
          </Link>
        </p>
      </header>
      <GateTimeline gates={turn.gates} policyVersion={turn.policyVersion} />
    </article>
  );
}
