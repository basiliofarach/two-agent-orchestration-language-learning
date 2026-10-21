/**
 * Applies one SSE payload once. A reconnect that replays an id is ignored.
 * The payload is the `TurnStreamEvent` JSON the BFF forwards; this class
 * does not import the server module that fetched it.
 */
export class LiveTurnEvents {
  private readonly seen = new Set<string>();

  accept(raw: string): string | null {
    const event = JSON.parse(raw) as {
      event_id: string;
      kind: string;
      turn_index: number;
      gate_name: string | null;
      decision: string | null;
      reason: string | null;
      action: string | null;
    };
    if (this.seen.has(event.event_id)) {
      return null;
    }
    this.seen.add(event.event_id);
    return this.line(event);
  }

  private line(event: {
    kind: string;
    turn_index: number;
    gate_name: string | null;
    decision: string | null;
    reason: string | null;
    action: string | null;
  }): string {
    const turn = `Turn ${event.turn_index + 1}`;
    if (event.kind === "prompt") {
      return `${turn} prompt received.`;
    }
    if (event.kind === "gate") {
      return `${turn} ${event.gate_name}: checked and passed. ${event.reason}`;
    }
    if (event.kind === "halt") {
      return `${turn} ${event.gate_name}: checked and fired (${event.decision}). ${event.reason}`;
    }
    if (event.kind === "skipped") {
      return `${turn} ${event.gate_name}: not reached. ${event.reason}`;
    }
    if (event.kind === "draft") {
      return `${turn} draft updated.`;
    }
    return `${turn} tutor ${event.action}.`;
  }
}
