import { describe, expect, it } from "vitest";

import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { SessionEvents } from "~/.server/session-events";

describe("SessionEvents", () => {
  it("resumes after a known id and replays when the id is unknown", async () => {
    const api = new FixtureTutorApi();
    const session = FixtureTutorApi.sessionIds.completed;
    const first = await api.events(session, null);
    const id = `${FixtureTutorApi.turnIds.completed}:prompt`;
    expect(first).toContain(`id: ${id}\n`);
    const resumed = await api.events(session, id);
    expect(resumed).not.toContain(`id: ${id}\n`);
    expect(
      resumed.startsWith(`retry: ${SessionEvents.RETRY_MILLISECONDS}`),
    ).toBe(true);
    const replayed = await api.events(session, "not-a-frame");
    expect(replayed).toContain(`id: ${id}\n`);
  });

  it("streams a halt and then no draft", async () => {
    const body = await new FixtureTutorApi().events(
      FixtureTutorApi.sessionIds.halted,
      null,
    );
    expect(body).toContain("event: halt\n");
    expect(body).toContain("event: skipped\n");
    expect(body).not.toContain("event: draft\n");
    const frames = body
      .split("\n\n")
      .filter((frame) => frame.startsWith("id:"));
    expect(frames.at(-1)).toContain("event: skipped");
  });
});
