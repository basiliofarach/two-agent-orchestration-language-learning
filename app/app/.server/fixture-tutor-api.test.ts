import { describe, expect, it } from "vitest";

import { ActionRejected } from "~/.server/action-rejected";
import { DashboardSource } from "~/.server/dashboard-source";
import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureLog } from "~/.server/fixture-log";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";

const completed = FixtureTutorApi.sessionIds.completed;
const halted = FixtureTutorApi.sessionIds.halted;
const turnId = FixtureTutorApi.turnIds.completed;

function command(
  action: "approve" | "edit" | "override" | "stop",
  sessionId: string = completed,
  editedOutput: string | null = null,
  id: string = turnId,
) {
  return {
    sessionId,
    turnId: id,
    tutorId: "tutor",
    action,
    editedOutput,
  };
}

async function logged(result: { setCookie: string | null }) {
  const api = new FixtureTutorApi(FixtureLog.parse(result.setCookie));
  return new DashboardSource(api, new TurnProjection(new DraftSegmenter()));
}

describe("FixtureTutorApi actions", () => {
  it("logs an approval against the turn and leaves the session open", async () => {
    const result = await new FixtureTutorApi().recordAction(command("approve"));
    const screen = await (await logged(result)).auditTurn(turnId);
    const human = screen.fields.find((field) => field.label === "Human action");
    expect(human?.value).toContain("approve by tutor");
    expect(screen.turn.statusLabel).toBe("Approved");
    const session = await (await logged(result)).session(completed);
    expect(session.open).toBe(true);
    expect(session.turns[0]?.statusLabel).toBe("Approved");
  });

  it("stops the session and keeps the recorded prompt", async () => {
    const result = await new FixtureTutorApi().recordAction(command("stop"));
    const source = await logged(result);
    const session = await source.session(completed);
    expect(session.open).toBe(false);
    expect(session.stoppedAt).toBeTruthy();
    expect(session.turns[0]?.prompt.text).toBe("How do I use ser?");
  });

  it("refuses to approve a halted turn", async () => {
    await expect(
      new FixtureTutorApi().recordAction(
        command("approve", halted, null, FixtureTutorApi.turnIds.halted),
      ),
    ).rejects.toBeInstanceOf(ActionRejected);
  });

  it("logs an edit and shows the tutor's wording", async () => {
    const result = await new FixtureTutorApi().recordAction(
      command("edit", completed, "Ser is for identity."),
    );
    const screen = await (await logged(result)).auditTurn(turnId);
    const human = screen.fields.find((field) => field.label === "Human action");
    expect(human?.value).toContain("edit by tutor");
    expect(human?.value).toContain("Ser is for identity.");
    expect(screen.turn.statusLabel).toBe("Edited");
  });

  it("stores an edit only after personal data is removed", async () => {
    const result = await new FixtureTutorApi().recordAction(
      command(
        "edit",
        completed,
        "Well done, my name is Ada. Email ada@example.com about 12 King Street.",
      ),
    );
    const screen = await (await logged(result)).auditTurn(turnId);
    const human = screen.fields.find((field) => field.label === "Human action");
    expect(human?.value).toContain("[REDACTED:person_name]");
    expect(human?.value).toContain("[REDACTED:email]");
    expect(human?.value).toContain("[REDACTED:postal_address]");
    expect(human?.value).not.toContain("Ada");
    expect(human?.value).not.toContain("ada@example.com");
    expect(human?.value).not.toContain("12 King Street");
  });

  it("refuses an unsafe edit and does not record it", async () => {
    const api = new FixtureTutorApi();
    await expect(
      api.recordAction(
        command("edit", completed, "Please diagnose this and search the web."),
      ),
    ).rejects.toThrow(
      "the edited reply cannot be released: This asks for the open web, which this tutor cannot use. This asks for medical advice a language tutor does not give.",
    );
    expect((await api.audit(completed)).actions).toEqual([]);
  });

  it("records a proficiency remark, which is not a refusal", async () => {
    const result = await new FixtureTutorApi().recordAction(
      command("edit", completed, "your level is A1, and ser agrees."),
    );
    const screen = await (await logged(result)).auditTurn(turnId);
    const human = screen.fields.find((field) => field.label === "Human action");
    expect(human?.value).toContain("your level is A1, and ser agrees.");
  });

  it("refuses an edit the browser could not store, instead of losing it", async () => {
    await expect(
      new FixtureTutorApi().recordAction(
        command("edit", completed, "x".repeat(5000)),
      ),
    ).rejects.toThrow("the fixture log is full");
  });

  it("refuses a second decision on the same turn", async () => {
    const first = await new FixtureTutorApi().recordAction(command("approve"));
    const api = new FixtureTutorApi(FixtureLog.parse(first.setCookie));
    await expect(api.recordAction(command("override"))).rejects.toThrow(
      "already has a tutor decision",
    );
  });
});
