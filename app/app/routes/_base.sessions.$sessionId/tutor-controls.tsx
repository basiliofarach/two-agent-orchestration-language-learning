import { cn } from "cn";
import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  OctagonX,
  PencilLine,
} from "lucide-react";
import type { ReactNode } from "react";
import { Form, useNavigation } from "react-router";

import { Panel, PanelNote } from "~/components/panel";
import { Button, buttonVariants } from "~/components/ui/button";
import { UtcTime } from "~/components/utc-time";
import { TutorControlOffer } from "~/lib/tutor-controls";
import { useHydrated } from "~/lib/use-hydrated";
import type { ActionView, TurnView, TutorActionName } from "~/lib/view-models";

const HINTS = {
  approve: "Release the checked draft to the learner as it stands.",
  edit: "Release your own wording instead. The edit is redacted and logged.",
  override: "Set the draft aside. Nothing from this turn reaches the learner.",
  stop: "End this learner's session. Every record is kept; no further turns or decisions can be logged.",
} as const satisfies Record<TutorActionName, string>;

const DECIDED = {
  approve: { label: "Approved", icon: CircleCheck },
  edit: { label: "Edited", icon: PencilLine },
  override: { label: "Overridden", icon: CircleSlash },
  stop: { label: "Session stopped", icon: OctagonX },
} as const satisfies Record<TutorActionName, unknown>;

/** A `<summary>` drawn as a button. Native disclosure: works before hydration. */
const SUMMARY =
  "list-none [&::-webkit-details-marker]:hidden cursor-pointer w-fit focus-visible:outline-none";

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
  actionError: { action: string; message: string } | null;
}) {
  const offer = TutorControlOffer.fromTurn(sessionOpen, turn, actions);
  const names = offer.names();
  const navigation = useNavigation();
  const hydrated = useHydrated();
  const pending =
    navigation.state !== "idle" &&
    navigation.formData?.get("turnId") === turn.turnId
      ? String(navigation.formData.get("action"))
      : null;
  const decisions = names.filter(
    (name): name is "approve" | "override" =>
      name === "approve" || name === "override",
  );

  return (
    <Panel title="Tutor decision">
      {actions.length > 0 ? <DecisionList actions={actions} /> : null}
      {!sessionOpen ? (
        <PanelNote>This session is stopped. Its record is preserved.</PanelNote>
      ) : null}
      {decisions.length > 0 || names.includes("edit") ? (
        <div className="space-y-3">
          {decisions.map((name) => (
            <ActionForm key={name} turnId={turn.turnId} action={name}>
              <Button
                type="submit"
                variant={name === "approve" ? "default" : "outline"}
                disabled={pending !== null}
                aria-describedby={`${turn.turnId}-${name}-hint`}
              >
                {pending === name
                  ? "Recording…"
                  : name === "approve"
                    ? "Approve"
                    : "Override"}
              </Button>
              <Hint id={`${turn.turnId}-${name}-hint`}>{HINTS[name]}</Hint>
            </ActionForm>
          ))}
          {names.includes("edit") ? (
            <details
              className="group space-y-3"
              open={actionError?.action === "edit"}
            >
              <summary
                className={cn(buttonVariants({ variant: "outline" }), SUMMARY)}
              >
                Edit reply
                <ChevronDown
                  aria-hidden="true"
                  className="transition-transform group-open:rotate-180"
                />
              </summary>
              <ActionForm turnId={turn.turnId} action="edit">
                <div className="w-full space-y-2">
                  <label
                    className="block text-sm font-medium"
                    htmlFor={`${turn.turnId}-edited`}
                  >
                    Edited reply
                  </label>
                  <Hint id={`${turn.turnId}-edit-hint`}>{HINTS.edit}</Hint>
                  <textarea
                    id={`${turn.turnId}-edited`}
                    name="editedOutput"
                    required
                    rows={4}
                    defaultValue={turn.draft?.afterChecks ?? ""}
                    readOnly={!hydrated}
                    aria-busy={!hydrated}
                    aria-describedby={`${turn.turnId}-edit-hint`}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                  <Button
                    type="submit"
                    disabled={!hydrated || pending !== null}
                  >
                    {pending === "edit" ? "Recording…" : "Save edited reply"}
                  </Button>
                </div>
              </ActionForm>
            </details>
          ) : null}
        </div>
      ) : null}
      {names.includes("stop") ? (
        <details className="group space-y-3 border-t pt-3">
          <summary
            className={cn(buttonVariants({ variant: "destructive" }), SUMMARY)}
          >
            Stop session
            <ChevronDown
              aria-hidden="true"
              className="transition-transform group-open:rotate-180"
            />
          </summary>
          <ActionForm turnId={turn.turnId} action="stop">
            <Hint id={`${turn.turnId}-stop-hint`}>{HINTS.stop}</Hint>
            <Button
              type="submit"
              variant="destructive"
              disabled={pending !== null}
              aria-describedby={`${turn.turnId}-stop-hint`}
            >
              {pending === "stop" ? "Recording…" : "Confirm stop session"}
            </Button>
          </ActionForm>
        </details>
      ) : null}
      {actionError ? (
        <p
          role="alert"
          className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive-text"
        >
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>Not recorded: {actionError.message}</span>
        </p>
      ) : null}
    </Panel>
  );
}

function ActionForm({
  turnId,
  action,
  children,
}: {
  turnId: string;
  action: TutorActionName;
  children: ReactNode;
}) {
  return (
    <Form
      method="post"
      preventScrollReset
      className="flex flex-wrap items-center gap-x-3 gap-y-2"
    >
      <input type="hidden" name="turnId" value={turnId} />
      <input type="hidden" name="action" value={action} />
      {children}
    </Form>
  );
}

function Hint({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="text-sm text-muted-foreground">
      {children}
    </p>
  );
}

function DecisionList({ actions }: { actions: ActionView[] }) {
  return (
    <ul className="space-y-3">
      {actions.map((action) => {
        const { label, icon: Icon } = DECIDED[action.action];
        return (
          <li
            key={`${action.action}-${action.actedAt}`}
            className="space-y-2 rounded-lg bg-muted/50 p-3 text-sm"
          >
            <p className="flex flex-wrap items-center gap-x-2">
              <Icon aria-hidden="true" className="size-4 shrink-0" />
              <span className="font-medium">{label}</span>
              <span className="text-muted-foreground">
                Tutor decision: {action.action} by {action.tutorId} ·{" "}
                <UtcTime iso={action.actedAt} />
              </span>
            </p>
            {action.editedOutput ? (
              <blockquote className="border-l-2 pl-3">
                {action.editedOutput}
              </blockquote>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
