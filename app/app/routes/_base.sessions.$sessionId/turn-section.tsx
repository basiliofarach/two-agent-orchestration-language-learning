import { useId } from "react";
import { Link } from "react-router";

import { ContextPanel } from "~/components/turn/context-panel";
import { DraftPanel } from "~/components/turn/draft-panel";
import { GateTimeline } from "~/components/turn/gate-timeline";
import { PromptPanel } from "~/components/turn/prompt-panel";
import { SafetyFlagPanel } from "~/components/turn/safety-flag-panel";
import { TurnStatusBadge } from "~/components/turn/turn-status-badge";
import type { ActionView, TurnView } from "~/lib/view-models";
import { TutorControls } from "./tutor-controls";

/** One turn as the tutor reviews it: what came in, what was used, what came out. */
export function TurnSection({
  turn,
  actions = [],
  sessionOpen = true,
  actionError = null,
}: {
  turn: TurnView;
  actions?: ActionView[];
  sessionOpen?: boolean;
  actionError?: { action: string; message: string } | null;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-4 border-t pt-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h2 id={headingId} className="text-lg font-medium">
            Turn {turn.turnIndex + 1}
          </h2>
          <TurnStatusBadge label={turn.statusLabel} />
        </div>
        <Link to={`/audit/${turn.turnId}`} className="text-sm underline">
          Audit record
        </Link>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <PromptPanel prompt={turn.prompt} />
        <ContextPanel context={turn.context} />
        <DraftPanel draft={turn.draft} />
        <SafetyFlagPanel flags={turn.flags} support={turn.support} />
      </div>
      <GateTimeline gates={turn.gates} policyVersion={turn.policyVersion} />
      <TutorControls
        turn={turn}
        actions={actions.filter((action) => action.turnId === turn.turnId)}
        sessionOpen={sessionOpen}
        actionError={actionError}
      />
    </section>
  );
}
