import { ArrowLeft } from "lucide-react";
import { data, Link, redirect, useActionData } from "react-router";

import { ActionRejected } from "~/.server/action-rejected";
import { CompositionRoot } from "~/.server/composition-root";
import { FixtureLog } from "~/.server/fixture-log";
import { RouteParams } from "~/.server/route-params";
import { TutorActionForm } from "~/.server/tutor-action-form";
import { SessionStatusBadge } from "~/components/session-status-badge";
import { ChainBreakNotice } from "~/components/turn/chain-break-notice";
import { ChainStatus } from "~/components/turn/chain-status";
import { UtcTime } from "~/components/utc-time";
import type { Route } from "./+types/route";
import { LiveTurnFeed } from "./live-turn-feed";
import { TurnSection } from "./turn-section";

export function meta({ loaderData }: Route.MetaArgs) {
  return [
    { title: loaderData ? `Session ${loaderData.sessionId}` : "Session" },
  ];
}

export async function loader({ request, params }: Route.LoaderArgs) {
  const sessionId = new RouteParams(params).uuid("sessionId", "Session");
  return new CompositionRoot(process.env, FixtureLog.from(request))
    .dashboardSource()
    .session(sessionId);
}

export async function action({ request, params }: Route.ActionArgs) {
  const sessionId = new RouteParams(params).uuid("sessionId", "Session");
  const body = await request.formData();
  const form = new TutorActionForm(body);
  const root = new CompositionRoot(process.env, FixtureLog.from(request));
  const postedTurn = body.get("turnId");
  const turnId = typeof postedTurn === "string" ? postedTurn : "";
  const postedAction = body.get("action");
  const named = typeof postedAction === "string" ? postedAction : "";
  try {
    const command = form.command(sessionId, root.tutorId());
    const recorded = await root.dashboardSource().recordAction(command);
    const headers = new Headers();
    if (recorded.setCookie !== null) {
      headers.set("Set-Cookie", recorded.setCookie);
    }
    return redirect(`/sessions/${sessionId}`, { headers });
  } catch (error) {
    if (error instanceof ActionRejected) {
      return data(
        { error: error.message, turnId, action: named },
        { status: 409 },
      );
    }
    throw error;
  }
}

export default function SessionRoute({ loaderData }: Route.ComponentProps) {
  const { chainBreak, turns } = loaderData;
  const actionData = useActionData<{
    error: string;
    turnId: string;
    action: string;
  }>();
  const failure = actionData && "error" in actionData ? actionData : null;
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          All sessions
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-medium">Session</h1>
          <SessionStatusBadge open={loaderData.open} />
        </div>
        <dl className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-muted-foreground">Learner</dt>
          <dd className="font-mono break-all">{loaderData.learnerId}</dd>
          <dt className="text-muted-foreground">Started</dt>
          <dd>
            <UtcTime iso={loaderData.startedAt} />
          </dd>
          {loaderData.stoppedAt ? (
            <>
              <dt className="text-muted-foreground">Stopped</dt>
              <dd>
                <UtcTime iso={loaderData.stoppedAt} />
              </dd>
            </>
          ) : null}
          <dt className="text-muted-foreground">Turns</dt>
          <dd>{turns.length}</dd>
        </dl>
        <ChainStatus chainBreak={chainBreak} />
        {loaderData.unchainedActions > 0 ? (
          <p className="text-sm text-muted-foreground">
            Unchained actions: {loaderData.unchainedActions} (listed, not
            verified).
          </p>
        ) : null}
      </header>
      {chainBreak ? <ChainBreakNotice chainBreak={chainBreak} /> : null}
      {turns.length === 0 && chainBreak === null ? (
        <p className="text-muted-foreground">This session has no turns.</p>
      ) : null}
      {turns.map((turn) => (
        <TurnSection
          key={turn.turnId}
          turn={turn}
          actions={loaderData.actions}
          sessionOpen={loaderData.open}
          actionError={
            failure?.turnId === turn.turnId
              ? { action: failure.action, message: failure.error }
              : null
          }
        />
      ))}
      <LiveTurnFeed
        sessionId={loaderData.sessionId}
        turns={turns}
        actions={loaderData.actions}
      />
    </div>
  );
}
