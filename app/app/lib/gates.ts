/** The four Article 14 gates in graph order (REQ-GATES, DEC-0005). */
export const GATE_ORDER = [
  "context_and_permission",
  "conflict_and_ambiguity",
  "sensitivity_and_high_stakes",
  "drift_and_anomaly",
] as const;

export type GateName = (typeof GATE_ORDER)[number];
