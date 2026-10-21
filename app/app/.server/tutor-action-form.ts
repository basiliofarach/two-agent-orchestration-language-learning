import { ActionRejected } from "~/.server/action-rejected";
import type { ActionCommand, TutorAction } from "~/.server/tutor-api.types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const ACTIONS: readonly TutorAction[] = ["approve", "edit", "override", "stop"];

/** The session route's form body, checked before it is logged. */
export class TutorActionForm {
  constructor(private readonly form: FormData) {}

  command(sessionId: string, tutorId: string): ActionCommand {
    const turnId = this.text("turnId");
    const action = this.text("action");
    const edited = this.form.get("editedOutput");
    if (!UUID.test(turnId)) {
      throw new ActionRejected("turn is not in this session");
    }
    if (!ACTIONS.includes(action as TutorAction)) {
      throw new ActionRejected("the action is not one the tutor can log");
    }
    const named = action as TutorAction;
    const editedOutput = typeof edited === "string" ? edited : null;
    if (named !== "edit" && editedOutput !== null && editedOutput !== "") {
      throw new ActionRejected(
        "edited_output is sent only when the tutor edits",
      );
    }
    if (named === "edit" && (editedOutput === null || !editedOutput.trim())) {
      throw new ActionRejected(
        "edited_output is required when the tutor edits",
      );
    }
    return {
      sessionId,
      turnId,
      tutorId,
      action: named,
      editedOutput: named === "edit" ? editedOutput : null,
    };
  }

  private text(name: string): string {
    const value = this.form.get(name);
    if (typeof value !== "string" || value.length === 0) {
      throw new ActionRejected("the action is not one the tutor can log");
    }
    return value;
  }
}
