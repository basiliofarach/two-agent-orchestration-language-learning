import { Ban, Check } from "lucide-react";
import { Link } from "react-router";

import { CompositionRoot } from "~/.server/composition-root";
import { FixtureLog } from "~/.server/fixture-log";
import { RouteParams } from "~/.server/route-params";
import { ChainStatus } from "~/components/turn/chain-status";
import { GateTimeline } from "~/components/turn/gate-timeline";
import { TurnStatusBadge } from "~/components/turn/turn-status-badge";
import { Badge } from "~/components/ui/badge";
import type { Route } from "./+types/_base.audit.$turnId";

export function meta({ loaderData }: Route.MetaArgs) {
  return [{ title: loaderData ? `Audit ${loaderData.turn.turnId}` : "Audit" }];
}

export async function loader({ request, params }: Route.LoaderArgs) {
  const turnId = new RouteParams(params).uuid("turnId", "Turn");
  return new CompositionRoot(process.env, FixtureLog.from(request))
    .dashboardSource()
    .auditTurn(turnId);
}

export default function AuditRoute({ loaderData }: Route.ComponentProps) {
  const { turn, recordIntact, fields, chainBreak, unchainedActions } =
    loaderData;
  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-medium">Audit record</h1>
        <p className="flex flex-wrap items-center gap-2">
          Turn {turn.turnIndex + 1}
          <TurnStatusBadge label={turn.statusLabel} />
          <Badge variant={recordIntact ? "secondary" : "destructive"}>
            {recordIntact ? (
              <Check aria-hidden="true" />
            ) : (
              <Ban aria-hidden="true" />
            )}
            {recordIntact
              ? "Record digest verified: intact"
              : "Record digest verified: broken"}
          </Badge>
        </p>
        <ChainStatus chainBreak={chainBreak} />
        {unchainedActions > 0 ? (
          <p>Unchained actions: {unchainedActions} (listed, not verified).</p>
        ) : null}
        <p>
          <Link to={`/sessions/${turn.sessionId}`} className="underline">
            Back to session
          </Link>
        </p>
      </header>
      <dl className="space-y-3">
        {fields.map((field) => (
          <div
            key={field.label}
            className="grid gap-1 sm:grid-cols-[16rem_1fr]"
          >
            <dt className="font-medium">{field.label}</dt>
            <dd className="whitespace-pre-line break-all">{field.value}</dd>
          </div>
        ))}
      </dl>
      <GateTimeline gates={turn.gates} policyVersion={turn.policyVersion} />
    </article>
  );
}
