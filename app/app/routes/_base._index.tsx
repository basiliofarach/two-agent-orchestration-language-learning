import { Link } from "react-router";

import { CompositionRoot } from "~/.server/composition-root";
import { SessionStatusBadge } from "~/components/session-status-badge";
import { UtcTime } from "~/components/utc-time";
import type { Route } from "./+types/_base._index";

export function meta(_: Route.MetaArgs) {
  return [{ title: "Tutor dashboard" }];
}

export async function loader() {
  return { sessions: await new CompositionRoot().dashboardSource().sessions() };
}

export default function Index({ loaderData }: Route.ComponentProps) {
  if (loaderData.sessions.length === 0) {
    return <p>No sessions yet.</p>;
  }
  return (
    <div>
      <h1 className="text-xl font-medium">Sessions</h1>
      <ul className="mt-4 divide-y">
        {loaderData.sessions.map((session) => (
          <li key={session.sessionId} className="space-y-1 py-3">
            <div className="flex items-center gap-3">
              <Link to={`/sessions/${session.sessionId}`} className="underline">
                Session {session.sessionId}
              </Link>
              <SessionStatusBadge open={session.open} />
            </div>
            <p className="text-sm text-muted-foreground">
              Learner {session.learnerId} · started{" "}
              <UtcTime iso={session.startedAt} />
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
