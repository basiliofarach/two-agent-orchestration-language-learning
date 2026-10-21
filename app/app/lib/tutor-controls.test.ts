import { describe, expect, it } from "vitest";

import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";
import { LiveTurnEvents } from "~/lib/live-turn-events";
import { TutorControlOffer } from "~/lib/tutor-controls";

async function turn(id: string) {
  const detail = await new FixtureTutorApi().turn(id);
  return new TurnProjection(new DraftSegmenter()).project(
    detail.record,
    detail.cited,
    detail.actions,
  );
}

describe("TutorControlOffer", () => {
  it("offers all four controls on a draft that passed every gate", async () => {
    const view = await turn(FixtureTutorApi.turnIds.completed);
    expect(TutorControlOffer.fromTurn(true, view, []).names()).toEqual([
      "approve",
      "edit",
      "override",
      "stop",
    ]);
  });

  it("does not offer approve or edit when the model did not run", async () => {
    const view = await turn(FixtureTutorApi.turnIds.halted);
    expect(TutorControlOffer.fromTurn(true, view, []).names()).toEqual([
      "override",
      "stop",
    ]);
  });

  it("offers only stop once the turn has a decision", async () => {
    const view = await turn(FixtureTutorApi.turnIds.completed);
    expect(
      TutorControlOffer.fromTurn(true, view, [
        {
          turnId: view.turnId,
          tutorId: "tutor",
          action: "approve",
          editedOutput: null,
          actedAt: "2026-10-21T12:00:00Z",
        },
      ]).names(),
    ).toEqual(["stop"]);
  });

  it("offers nothing once the session is stopped", async () => {
    const view = await turn(FixtureTutorApi.turnIds.completed);
    expect(TutorControlOffer.fromTurn(false, view, []).names()).toEqual([]);
  });
});

describe("LiveTurnEvents", () => {
  it("ignores an event id it has already applied", () => {
    const feed = new LiveTurnEvents();
    const payload = JSON.stringify({
      event_id: "turn:prompt",
      kind: "prompt",
      turn_index: 0,
      gate_name: null,
      decision: null,
      reason: null,
      action: null,
    });
    expect(feed.accept(payload)).toBe("Turn 1 prompt received.");
    expect(feed.accept(payload)).toBeNull();
  });

  it("describes a halt without treating it as a draft", () => {
    const feed = new LiveTurnEvents();
    const line = feed.accept(
      JSON.stringify({
        event_id: "turn:conflict",
        kind: "halt",
        turn_index: 0,
        gate_name: "conflict_and_ambiguity",
        decision: "stop",
        reason: "The retrieved notes disagree.",
        action: null,
      }),
    );
    expect(line).toContain("checked and fired (stop)");
    expect(line).not.toContain("draft updated");
  });
});
