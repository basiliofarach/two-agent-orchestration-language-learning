import type { ActionView, TurnView, TutorActionName } from "~/lib/view-models";

const DECISIONS = new Set<TutorActionName>(["approve", "edit", "override"]);

/**
 * Which of the four tutor controls the backend will log for this turn.
 *
 * A control that `RecordHumanAction` would reject is not offered
 * (REQ-DASH). The messages match that service so a refused post says the
 * same thing the button hid.
 */
export class TutorControlOffer {
  constructor(
    private readonly sessionOpen: boolean,
    private readonly modelRan: boolean,
    private readonly refused: boolean,
    private readonly allGatesPassed: boolean,
    private readonly hasDecision: boolean,
  ) {}

  static fromTurn(
    sessionOpen: boolean,
    turn: TurnView,
    actions: ActionView[],
  ): TutorControlOffer {
    return new TutorControlOffer(
      sessionOpen,
      turn.modelRan,
      turn.refused,
      turn.allGatesPassed,
      actions.some((action) => DECISIONS.has(action.action)),
    );
  }

  names(): TutorActionName[] {
    if (!this.sessionOpen) {
      return [];
    }
    const names: TutorActionName[] = [];
    if (!this.hasDecision) {
      if (this.modelRan && !this.refused && this.allGatesPassed) {
        names.push("approve");
      }
      if (this.modelRan) {
        names.push("edit");
      }
      names.push("override");
    }
    names.push("stop");
    return names;
  }

  refusal(action: TutorActionName): string {
    if (!this.sessionOpen) {
      return "session is stopped";
    }
    if (action !== "stop" && this.hasDecision) {
      return "this turn already has a tutor decision";
    }
    if ((action === "approve" || action === "edit") && !this.modelRan) {
      return "the model did not run on this turn, so there is no draft to release";
    }
    if (action === "approve" && this.refused) {
      return "the agent refused this draft; edit or override it instead";
    }
    if (action === "approve" && !this.allGatesPassed) {
      return "this draft did not pass every gate; edit or override it instead";
    }
    return "the action is not one the tutor can log";
  }
}
