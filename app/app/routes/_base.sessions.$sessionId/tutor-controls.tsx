import { Form } from "react-router";

import { Button } from "~/components/ui/button";
import { TutorControlOffer } from "~/lib/tutor-controls";
import type { ActionView, TurnView } from "~/lib/view-models";

const LABELS = {
  approve: "Approve",
  edit: "Save edited reply",
  override: "Override",
  stop: "Stop session",
} as const;

/**
 * The four tutor controls. A control `RecordHumanAction` would reject is
 * absent, so the page never offers an action the backend cannot log.
 */
export function TutorControls({
  turn,
  actions,
  sessionOpen,
  actionError,
}: {
  turn: TurnView;
  actions: ActionView[];
  sessionOpen: boolean;
  actionError: string | null;
}) {
  const offer = TutorControlOffer.fromTurn(sessionOpen, turn, actions);
  const names = offer.names();
  if (names.length === 0 && actions.length === 0) {
    return (
      <p className="text-muted-foreground">
        This session is stopped. Its record is preserved.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {actions.length > 0 ? <DecisionList actions={actions} /> : null}
      {names.includes("edit") ? (
        <Form method="post" className="space-y-2">
          <input type="hidden" name="turnId" value={turn.turnId} />
          <input type="hidden" name="action" value="edit" />
          <label className="block space-y-2">
            <span className="text-sm font-medium">Edited reply</span>
            <textarea
              name="editedOutput"
              required
              rows={4}
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
            />
          </label>
          <Button type="submit">{LABELS.edit}</Button>
        </Form>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {names
          .filter((name) => name !== "edit")
          .map((name) => (
            <Form method="post" key={name}>
              <input type="hidden" name="turnId" value={turn.turnId} />
              <input type="hidden" name="action" value={name} />
              <Button
                type="submit"
                variant={name === "stop" ? "destructive" : "default"}
              >
                {LABELS[name]}
              </Button>
            </Form>
          ))}
      </div>
      {actionError ? <p role="alert">{actionError}</p> : null}
    </div>
  );
}

function DecisionList({ actions }: { actions: ActionView[] }) {
  return (
    <ul className="space-y-2">
      {actions.map((action) => (
        <li key={`${action.action}-${action.actedAt}`}>
          <p>
            Tutor decision: {action.action} by {action.tutorId}
          </p>
          {action.editedOutput ? <p>{action.editedOutput}</p> : null}
        </li>
      ))}
    </ul>
  );
}
