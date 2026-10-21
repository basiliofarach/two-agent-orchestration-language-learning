import { ArrowLeft, Ban, Check } from "lucide-react";
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

/** Identifiers and digests an examiner compares character by character. */
const MONOSPACE = new Set([
  "Retrieved context identifiers",
  "Model revision",
  "Policy version",
  "Previous record hash",
  "Record hash",
]);

export default function AuditRoute({ loaderData }: Route.ComponentProps) {
  const { turn, recordIntact, fields, chainBreak, unchainedActions } =
    loaderData;
  return (
    <article className="space-y-6">
      <header className="space-y-3">
        <Link
          to={`/sessions/${turn.sessionId}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Back to session
        </Link>
        <h1 className="text-2xl font-medium">Audit record</h1>
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
          <p className="text-sm text-muted-foreground">
            Unchained actions: {unchainedActions} (listed, not verified).
          </p>
        ) : null}
      </header>
      <section aria-labelledby="audit-fields" className="space-y-3">
        <h2 id="audit-fields" className="text-lg font-medium">
          Per-turn record
        </h2>
        <dl className="divide-y rounded-xl border">
          {fields.map((field) => (
            <div
              key={field.label}
              className="grid gap-1 px-4 py-3 sm:grid-cols-[16rem_1fr] sm:gap-4"
            >
              <dt className="text-sm font-medium text-muted-foreground">
                {field.label}
              </dt>
              <dd
                className={`whitespace-pre-line break-all ${MONOSPACE.has(field.label) ? "font-mono text-sm" : ""}`}
              >
                {field.value}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <GateTimeline gates={turn.gates} policyVersion={turn.policyVersion} />
    </article>
  );
}
