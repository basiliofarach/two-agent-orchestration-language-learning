export const SIMULATION_BANNER =
  "Simulated campaign — no real learner or tutor";

/**
 * Persistent notice for simulation mode. The words carry the meaning;
 * the border is only a second cue.
 */
export function SimulationBanner() {
  return (
    <p
      role="status"
      className="border-b border-foreground bg-background px-4 py-2 text-center text-sm font-medium"
    >
      {SIMULATION_BANNER}
    </p>
  );
}
