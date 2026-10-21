/** The four Article 14 gates in graph order (REQ-GATES, DEC-0005). */
export const GATE_ORDER = [
  "context_and_permission",
  "conflict_and_ambiguity",
  "sensitivity_and_high_stakes",
  "drift_and_anomaly",
] as const;

export type GateName = (typeof GATE_ORDER)[number];

/** How a gate is named to the tutor, on the timeline and in the live feed. */
export const GATE_LABELS: Record<GateName, string> = {
  context_and_permission: "Context and permission",
  conflict_and_ambiguity: "Conflict and ambiguity",
  sensitivity_and_high_stakes: "Sensitivity and high-stakes",
  drift_and_anomaly: "Drift and anomaly",
};
