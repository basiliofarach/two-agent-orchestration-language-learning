import { GATE_LABELS, type GateName } from "~/lib/gates";

export type LiveKind =
  | "prompt"
  | "gate"
  | "halt"
  | "skipped"
  | "draft"
  | "action";

/** One painted line of the live feed. */
export type LiveLine = {
  id: string;
  turnId: string;
  turnIndex: number;
  kind: LiveKind;
  text: string;
};

type LivePayload = {
  event_id: string;
  kind: LiveKind;
  turn_id: string;
  turn_index: number;
  gate_name: string | null;
  decision: string | null;
  reason: string | null;
  action: string | null;
};

/**
 * Applies one SSE payload once. A reconnect that replays an id is ignored.
 * The payload is the `TurnStreamEvent` JSON the BFF forwards; this class
 * does not import the server module that fetched it.
 */
export class LiveTurnEvents {
  private readonly seen = new Set<string>();

  accept(raw: string): LiveLine | null {
    const event = JSON.parse(raw) as LivePayload;
    if (this.seen.has(event.event_id)) {
      return null;
    }
    this.seen.add(event.event_id);
    return {
      id: event.event_id,
      turnId: event.turn_id,
      turnIndex: event.turn_index,
      kind: event.kind,
      text: this.line(event),
    };
  }

  private line(event: LivePayload): string {
    const turn = `Turn ${event.turn_index + 1}`;
    const gate = this.gate(event.gate_name);
    if (event.kind === "prompt") {
      return `${turn} prompt received.`;
    }
    if (event.kind === "gate") {
      return `${turn} ${gate}: checked and passed. ${event.reason}`;
    }
    if (event.kind === "halt") {
      return `${turn} ${gate}: checked and fired (${event.decision}). ${event.reason}`;
    }
    if (event.kind === "skipped") {
      return `${turn} ${gate}: not reached. ${event.reason}`;
    }
    if (event.kind === "draft") {
      return `${turn} draft updated.`;
    }
    return `${turn} tutor ${event.action}.`;
  }

  private gate(name: string | null): string {
    return name !== null && name in GATE_LABELS
      ? GATE_LABELS[name as GateName]
      : String(name);
  }
}

/**
 * What the painted lines say about the page around them.
 *
 * `behind` compares the stream with the loader data: a turn the page has
 * not loaded, or more tutor actions on a turn than the page shows, means
 * the panels are stale and the route should revalidate.
 */
export class LiveTurnSummary {
  constructor(private readonly lines: readonly LiveLine[]) {}

  /** The latest turn halted at a gate and produced no draft. */
  latestHalted(): boolean {
    const latest = Math.max(-1, ...this.lines.map((line) => line.turnIndex));
    const kinds = this.lines
      .filter((line) => line.turnIndex === latest)
      .map((line) => line.kind);
    return kinds.includes("halt") && !kinds.includes("draft");
  }

  behind(
    loadedTurnIds: readonly string[],
    loadedActions: ReadonlyMap<string, number>,
  ): boolean {
    const loaded = new Set(loadedTurnIds);
    const streamed = new Map<string, number>();
    for (const line of this.lines) {
      if (!loaded.has(line.turnId)) {
        return true;
      }
      if (line.kind === "action") {
        streamed.set(line.turnId, (streamed.get(line.turnId) ?? 0) + 1);
      }
    }
    for (const [turnId, count] of streamed) {
      if (count > (loadedActions.get(turnId) ?? 0)) {
        return true;
      }
    }
    return false;
  }
}
