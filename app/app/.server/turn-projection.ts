import type { DraftSegmenter } from "~/.server/draft-segmenter";
import type {
  CitedSnippetJson,
  GateDecision,
  GateEvaluationJson,
  HumanActionJson,
  TurnRecordJson,
} from "~/.server/tutor-api.types";
import { GATE_LABELS, GATE_ORDER } from "~/lib/gates";
import type {
  ActionView,
  DraftView,
  GateState,
  GateView,
  SnippetView,
  TurnStatusLabel,
  TurnView,
} from "~/lib/view-models";

/** Turns one audit record into the tutor-facing `TurnView`. */
export class TurnProjection {
  constructor(private readonly segmenter: DraftSegmenter) {}

  project(
    record: TurnRecordJson,
    cited: CitedSnippetJson[],
    actions: HumanActionJson[] = [],
  ): TurnView {
    const gates = this.gates(record.gate_evaluations);
    const refused = record.refused === true;
    const context = this.retrievalReached(gates)
      ? cited.map((snippet, index) => this.snippet(snippet, index + 1))
      : null;
    const projected = actions.map((action) => this.action(action));
    return {
      turnId: record.turn_id,
      sessionId: record.session_id,
      turnIndex: record.turn_index,
      policyVersion: record.policy_version,
      statusLabel: this.status(refused, gates, projected),
      modelRan: record.output_before_checks !== null,
      refused,
      allGatesPassed:
        gates.length === GATE_ORDER.length &&
        gates.every((gate) => gate.state === "passed"),
      prompt: {
        text: record.learner_prompt.text,
        redactedCategories: [...record.learner_prompt.redacted_categories],
      },
      context,
      draft: this.draft(record, refused, context ?? []),
      gates,
      support: record.source_support
        ? { ratio: record.source_support.support_ratio }
        : null,
      flags: record.safety_flags
        ? record.safety_flags.map((flag) => ({ ...flag }))
        : null,
    };
  }

  action(record: HumanActionJson): ActionView {
    return {
      turnId: record.turn_id,
      tutorId: record.tutor_id,
      action: record.action,
      editedOutput: record.edited_output,
      actedAt: record.acted_at,
    };
  }

  private draft(
    record: TurnRecordJson,
    refused: boolean,
    context: SnippetView[],
  ): DraftView | null {
    if (record.output_after_checks === null) {
      return null;
    }
    const citations = new Map(
      context.map((snippet) => [snippet.chunkId, snippet.citation]),
    );
    return {
      segments: this.segmenter.segment(
        record.output_after_checks,
        record.source_support,
        citations,
      ),
      afterChecks: record.output_after_checks,
      beforeChecks: record.output_before_checks,
      disclosure: record.ai_disclosure,
      refused,
    };
  }

  private retrievalReached(gates: GateView[]): boolean {
    return gates.some(
      (gate) =>
        gate.name === "context_and_permission" && gate.state === "passed",
    );
  }

  private status(
    refused: boolean,
    gates: GateView[],
    actions: ActionView[],
  ): TurnStatusLabel {
    const decision = actions.find((action) => action.action !== "stop");
    if (decision?.action === "approve") {
      return "Approved";
    }
    if (decision?.action === "edit") {
      return "Edited";
    }
    if (decision?.action === "override") {
      return "Overridden";
    }
    if (refused) {
      return "Refused";
    }
    if (gates.some((gate) => gate.state === "fired")) {
      return "Held for review";
    }
    return "Awaiting tutor approval";
  }

  private snippet(cited: CitedSnippetJson, citation: number): SnippetView {
    return {
      chunkId: cited.chunk_id,
      citation,
      content: cited.content,
      sourceUri: cited.source.source_uri,
      version: cited.source.version,
      reviewStatus: cited.source.review_status,
    };
  }

  private gates(evaluations: GateEvaluationJson[]): GateView[] {
    const byName = new Map(evaluations.map((row) => [row.gate_name, row]));
    const halted = evaluations.find(
      (row) => row.decision === "pause" || row.decision === "stop",
    );
    return GATE_ORDER.map((name) => {
      const row = byName.get(name);
      if (!row) {
        return {
          name,
          label: GATE_LABELS[name],
          state: "not_reached",
          stateText: "Not reached",
          reason: halted
            ? `Not reached because ${halted.policy_rule_id} held the turn.`
            : "No evaluation was recorded.",
          policyRuleId: halted?.policy_rule_id ?? "not_recorded",
        };
      }
      return {
        name,
        label: GATE_LABELS[name],
        state: this.state(row.decision),
        stateText: this.stateText(row.decision),
        reason: row.reason,
        policyRuleId: row.policy_rule_id,
      };
    });
  }

  private state(decision: GateDecision): GateState {
    if (decision === "pass") {
      return "passed";
    }
    if (decision === "not_evaluated") {
      return "not_reached";
    }
    return "fired";
  }

  private stateText(decision: GateDecision): string {
    if (decision === "pass") {
      return "Checked and passed";
    }
    if (decision === "not_evaluated") {
      return "Not reached";
    }
    return `Checked and fired (${decision})`;
  }
}
