import { describe, expect, it } from "vitest";

import {
  type LiveLine,
  LiveTurnEvents,
  LiveTurnSummary,
} from "~/lib/live-turn-events";

function payload(fields: Record<string, unknown>): string {
  return JSON.stringify({
    event_id: "t1:prompt",
    kind: "prompt",
    turn_id: "t1",
    turn_index: 0,
    gate_name: null,
    decision: null,
    reason: null,
    action: null,
    ...fields,
  });
}

function line(fields: Partial<LiveLine>): LiveLine {
  return {
    id: "t1:prompt",
    turnId: "t1",
    turnIndex: 0,
    kind: "prompt",
    text: "",
    ...fields,
  };
}

describe("LiveTurnEvents", () => {
  it("paints a replayed event id once", () => {
    const events = new LiveTurnEvents();
    expect(events.accept(payload({}))?.text).toBe("Turn 1 prompt received.");
    expect(events.accept(payload({}))).toBeNull();
  });

  it("names a fired gate and its decision", () => {
    const accepted = new LiveTurnEvents().accept(
      payload({
        event_id: "t1:conflict_and_ambiguity",
        kind: "halt",
        gate_name: "conflict_and_ambiguity",
        decision: "stop",
        reason: "Notes disagree.",
      }),
    );
    expect(accepted).toMatchObject({ kind: "halt", turnId: "t1" });
    expect(accepted?.text).toBe(
      "Turn 1 Conflict and ambiguity: checked and fired (stop). Notes disagree.",
    );
  });
});

describe("LiveTurnSummary", () => {
  it("reports the latest turn as halted only when it has no draft", () => {
    const halted = [line({ kind: "prompt" }), line({ id: "h", kind: "halt" })];
    expect(new LiveTurnSummary(halted).latestHalted()).toBe(true);
    const later = [
      ...halted,
      line({ id: "t2", turnId: "t2", turnIndex: 1, kind: "draft" }),
    ];
    expect(new LiveTurnSummary(later).latestHalted()).toBe(false);
  });

  it("is behind when the stream names a turn the page has not loaded", () => {
    const summary = new LiveTurnSummary([line({ turnId: "t2" })]);
    expect(summary.behind(["t1"], new Map())).toBe(true);
    expect(summary.behind(["t1", "t2"], new Map())).toBe(false);
  });

  it("is behind when the stream has more tutor actions than the page shows", () => {
    const summary = new LiveTurnSummary([
      line({}),
      line({ id: "t1:action:0", kind: "action" }),
    ]);
    expect(summary.behind(["t1"], new Map())).toBe(true);
    expect(summary.behind(["t1"], new Map([["t1", 1]]))).toBe(false);
  });
});
