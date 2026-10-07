/** JSON shapes of the FastAPI read endpoints the dashboard calls. */
import type { GateName } from "~/lib/gates";

export type GateDecision = "pass" | "pause" | "stop" | "not_evaluated";

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

export type TurnRecordJson = {
  turn_id: string;
  session_id: string;
  turn_index: number;
  learner_prompt: { text: string; redacted_categories: string[] };
  output_before_checks: string | null;
  output_after_checks: string | null;
  ai_disclosure: string | null;
  refused: boolean | null;
  safety_flags: SafetyFlagJson[] | null;
  source_support: SourceSupportJson | null;
  gate_evaluations: GateEvaluationJson[];
  policy_version: string;
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

/** `AuditView` in tutor-core; only the fields the dashboard reads. */
export type AuditJson = {
  records: TurnRecordJson[];
  intact: boolean;
  break_turn_id: string | null;
  break_reason: "tampered" | "excised" | "unreadable" | null;
};

/** `TurnDetail` in tutor-core. */
export type TurnDetailJson = {
  record: TurnRecordJson;
  cited: CitedSnippetJson[];
  record_intact: boolean;
};
