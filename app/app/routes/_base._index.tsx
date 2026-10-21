import { ChevronRight } from "lucide-react";
import { Link } from "react-router";

import { CompositionRoot } from "~/.server/composition-root";
import { FixtureLog } from "~/.server/fixture-log";
import { SessionStatusBadge } from "~/components/session-status-badge";
import { UtcTime } from "~/components/utc-time";
import type { Route } from "./+types/_base._index";

export function meta(_: Route.MetaArgs) {
  return [{ title: "Tutor dashboard" }];
}

export async function loader({ request }: Route.LoaderArgs) {
  return {
    sessions: await new CompositionRoot(process.env, FixtureLog.from(request))
      .dashboardSource()
      .sessions(),
  };
}

export default function Index({ loaderData }: Route.ComponentProps) {
  const { sessions } = loaderData;
  const open = sessions.filter((session) => session.open).length;
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-medium">Sessions</h1>
        <p className="text-sm text-muted-foreground">
          {sessions.length === 0
            ? "No sessions yet. A session appears here when a learner starts one."
            : `${sessions.length} ${sessions.length === 1 ? "session" : "sessions"} · ${open} open`}
        </p>
      </header>
      {sessions.length > 0 ? (
        <ul className="divide-y rounded-xl border">
          {sessions.map((session) => (
            <li key={session.sessionId}>
              <Link
                to={`/sessions/${session.sessionId}`}
                className="group flex items-center gap-4 px-4 py-3 outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 first:rounded-t-xl last:rounded-b-xl"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-medium break-all underline-offset-4 group-hover:underline">
                      Session {session.sessionId}
                    </span>
                    <SessionStatusBadge open={session.open} />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Learner {session.learnerId} · started{" "}
                    <UtcTime iso={session.startedAt} />
                    {session.stoppedAt ? (
                      <>
                        {" "}
                        · stopped <UtcTime iso={session.stoppedAt} />
                      </>
                    ) : null}
                  </p>
                </div>
                <ChevronRight
                  aria-hidden="true"
                  className="size-4 shrink-0 text-muted-foreground"
                />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
