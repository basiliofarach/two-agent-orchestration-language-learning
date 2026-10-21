/** JSON shapes of the FastAPI endpoints the dashboard calls. */
import type { GateName } from "~/lib/gates";

export type GateDecision = "pass" | "pause" | "stop" | "not_evaluated";

export type TutorAction = "approve" | "edit" | "override" | "stop";

export type GateEvaluationJson = {
  gate_name: GateName;
  decision: GateDecision;
  reason: string;
  policy_rule_id: string;
};

export type SpanJson = {
  text: string;
  start: number;
  end: number;
  source_ids: string[];
};

export type SourceSupportJson = {
  supported: SpanJson[];
  unsupported: SpanJson[];
  support_ratio: number;
};

export type SafetyFlagJson = {
  category: string;
  message: string;
  severity: "low" | "medium" | "high";
};

export type DecodingParamsJson = {
  temperature: number;
  top_p: number;
  max_tokens: number;
};

export type TurnRecordJson = {
  turn_id: string;
  session_id: string;
  turn_index: number;
  learner_prompt: { text: string; redacted_categories: string[] };
  retrieved_context_ids: string[];
  model_revision: string | null;
  template_version: string | null;
  decoding_params: DecodingParamsJson | null;
  output_before_checks: string | null;
  output_after_checks: string | null;
  ai_disclosure: string | null;
  refused: boolean | null;
  safety_flags: SafetyFlagJson[] | null;
  source_support: SourceSupportJson | null;
  gate_evaluations: GateEvaluationJson[];
  policy_version: string;
  previous_record_hash: string;
  record_hash: string;
  recorded_at: string;
};

export type HumanActionJson = {
  turn_id: string;
  tutor_id: string;
  action: TutorAction;
  edited_output: string | null;
  acted_at: string;
  session_id: string | null;
  action_index: number | null;
  previous_action_hash: string | null;
  action_hash: string | null;
};

export type CitedSnippetJson = {
  chunk_id: string;
  content: string;
  source: { source_uri: string; version: string; review_status: string };
};

/** `SessionSummary` in tutor-core. */
export type SessionSummaryJson = {
  session_id: string;
  learner_id: string;
  started_at: string;
  stopped_at: string | null;
  open: boolean;
};

/** `AuditView` in tutor-core. */
export type AuditJson = {
  records: TurnRecordJson[];
  actions: HumanActionJson[];
  intact: boolean;
  break_turn_id: string | null;
  break_reason: "tampered" | "excised" | "unreadable" | null;
  action_break_index: number | null;
  unchained_actions: number;
};

/** `TurnDetail` in tutor-core. The session object on the wire is not read. */
export type TurnDetailJson = {
  record: TurnRecordJson;
  actions: HumanActionJson[];
  cited: CitedSnippetJson[];
  record_intact: boolean;
};

/** `RecordedAction` in tutor-core. */
export type RecordedActionJson = {
  action: HumanActionJson;
  stopped: boolean;
};

export type ActionCommand = {
  sessionId: string;
  turnId: string;
  tutorId: string;
  action: TutorAction;
  editedOutput: string | null;
};

export type RecordedActionResult = {
  action: HumanActionJson;
  setCookie: string | null;
};

export type StreamKind =
  | "prompt"
  | "gate"
  | "halt"
  | "skipped"
  | "draft"
  | "action";

/** `TurnStreamEvent` in tutor-core. */
export type StreamEventJson = {
  event_id: string;
  kind: StreamKind;
  turn_id: string;
  session_id: string;
  turn_index: number;
  gate_name: GateName | null;
  decision: GateDecision | null;
  reason: string | null;
  policy_rule_id: string | null;
  action: TutorAction | null;
  text: string | null;
};
