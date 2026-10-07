import { describe, expect, it } from "vitest";

import { DashboardSource } from "~/.server/dashboard-source";
import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";
import type { AuditJson } from "~/.server/tutor-api.types";

const { completed, halted } = FixtureTutorApi.sessionIds;

/** Fixture data with the audit chain verdict replaced. */
class BrokenChainApi extends FixtureTutorApi {
  constructor(
    private readonly verdict: Omit<AuditJson, "records"> & {
      records?: AuditJson["records"];
    },
  ) {
    super();
  }

  override async audit(sessionId: string): Promise<AuditJson> {
    const audit = await super.audit(sessionId);
    return { ...audit, ...this.verdict };
  }
}

function source(api = new FixtureTutorApi()) {
  return new DashboardSource(api, new TurnProjection(new DraftSegmenter()));
}

describe("DashboardSource", () => {
  it("lists sessions in tutor-facing fields", async () => {
    const sessions = await source().sessions();
    expect(sessions).toHaveLength(3);
    expect(sessions[0]).toEqual({
      sessionId: completed,
      learnerId: "10000000-0000-4000-8000-000000000001",
      open: true,
      startedAt: "2026-10-01T09:00:00Z",
    });
  });

  it("projects every turn of an intact session", async () => {
    const screen = await source().session(halted);
    expect(screen.chainBreak).toBeNull();
    expect(screen.turns.map((turn) => turn.statusLabel)).toEqual([
      "Held for review",
    ]);
  });

  it("reports a tampered record as tampered, not as unreadable", async () => {
    const api = new BrokenChainApi({
      intact: false,
      break_turn_id: FixtureTutorApi.turnIds.completed,
      break_reason: "tampered",
    });
    const screen = await source(api).session(completed);
    expect(screen.chainBreak).toEqual({
      turnId: FixtureTutorApi.turnIds.completed,
      reason: "tampered",
    });
    expect(screen.turns).toHaveLength(1);
  });

  it("reports an unreadable record with no turns to show", async () => {
    const api = new BrokenChainApi({
      records: [],
      intact: false,
      break_turn_id: FixtureTutorApi.turnIds.completed,
      break_reason: "unreadable",
    });
    const screen = await source(api).session(completed);
    expect(screen.chainBreak?.reason).toBe("unreadable");
    expect(screen.turns).toEqual([]);
  });

  it("refuses to guess when a break is reported without a reason", async () => {
    const api = new BrokenChainApi({
      intact: false,
      break_turn_id: FixtureTutorApi.turnIds.completed,
      break_reason: null,
    });
    await expect(source(api).session(completed)).rejects.toThrow(
      "without naming it",
    );
  });

  it("returns one turn and its digest check for the audit route", async () => {
    const screen = await source().auditTurn(FixtureTutorApi.turnIds.refused);
    expect(screen.recordIntact).toBe(true);
    expect(screen.turn.statusLabel).toBe("Refused");
  });

  it("answers an unknown session with a 404 response", async () => {
    await expect(
      source().session("99999999-9999-4999-8999-999999999999"),
    ).rejects.toMatchObject({ status: 404 });
  });
});
