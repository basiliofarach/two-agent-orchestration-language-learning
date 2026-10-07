/**
 * What the tutor's browser receives. Loaders return these and nothing else;
 * audit fields the UI must not show are dropped before they get here.
 *
 * `null` always means "this stage was not reached", never "empty".
 */
import type { GateName } from "~/lib/gates";

export type GateState = "passed" | "fired" | "not_reached";

export type GateView = {
  name: GateName;
  label: string;
  state: GateState;
  stateText: string;
  reason: string;
  policyRuleId: string;
};

export type Severity = "low" | "medium" | "high";

export type FlagView = {
  category: string;
  message: string;
  severity: Severity;
};

export type SnippetView = {
  chunkId: string;
  /** 1-based number the draft's citations refer to. */
  citation: number;
  content: string;
  sourceUri: string;
  version: string;
  reviewStatus: string;
};

export type DraftSegment =
  | { kind: "plain"; start: number; text: string }
  | { kind: "supported"; start: number; text: string; citations: string[] }
  | { kind: "unsupported"; start: number; text: string };

export type DraftView = {
  segments: DraftSegment[];
  beforeChecks: string | null;
  disclosure: string | null;
  refused: boolean;
};

export type TurnStatusLabel =
  | "Refused"
  | "Held for review"
  | "Awaiting tutor approval";

export type TurnView = {
  turnId: string;
  sessionId: string;
  turnIndex: number;
  policyVersion: string;
  statusLabel: TurnStatusLabel;
  prompt: { text: string; redactedCategories: string[] };
  context: SnippetView[] | null;
  draft: DraftView | null;
  gates: GateView[];
  support: { ratio: number } | null;
  flags: FlagView[] | null;
};

export type ChainBreakReason = "tampered" | "excised" | "unreadable";

export type ChainBreak = {
  turnId: string;
  reason: ChainBreakReason;
};

export type SessionListItem = {
  sessionId: string;
  learnerId: string;
  open: boolean;
  startedAt: string;
};

export type SessionScreen = {
  sessionId: string;
  learnerId: string;
  open: boolean;
  startedAt: string;
  turns: TurnView[];
  chainBreak: ChainBreak | null;
};

export type AuditScreen = {
  turn: TurnView;
  recordIntact: boolean;
};
