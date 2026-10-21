import { data, redirect, useActionData } from "react-router";

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
      return data({ error: error.message, turnId }, { status: 409 });
    }
    throw error;
  }
}

export default function SessionRoute({ loaderData }: Route.ComponentProps) {
  const { chainBreak, turns } = loaderData;
  const actionData = useActionData<{ error: string; turnId: string }>();
  const failure = actionData && "error" in actionData ? actionData : null;
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
          {loaderData.stoppedAt ? (
            <>
              {" "}
              · stopped <UtcTime iso={loaderData.stoppedAt} />
            </>
          ) : null}
        </p>
        <ChainStatus chainBreak={chainBreak} />
        {loaderData.unchainedActions > 0 ? (
          <p>
            Unchained actions: {loaderData.unchainedActions} (listed, not
            verified).
          </p>
        ) : null}
      </header>
      {chainBreak ? <ChainBreakNotice chainBreak={chainBreak} /> : null}
      {turns.length === 0 && chainBreak === null ? (
        <p>This session has no turns.</p>
      ) : null}
      {turns.map((turn) => (
        <TurnSection
          key={turn.turnId}
          turn={turn}
          actions={loaderData.actions}
          sessionOpen={loaderData.open}
          actionError={failure?.turnId === turn.turnId ? failure.error : null}
        />
      ))}
      <LiveTurnFeed sessionId={loaderData.sessionId} />
    </div>
  );
}
