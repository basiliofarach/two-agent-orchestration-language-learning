import { describe, expect, it } from "vitest";

import { FixtureLog } from "~/.server/fixture-log";
import type { HumanActionJson } from "~/.server/tutor-api.types";

function action(
  name: HumanActionJson["action"],
  index: number,
  edited: string | null = null,
): HumanActionJson {
  return {
    turn_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    tutor_id: "tutor",
    action: name,
    edited_output: edited,
    acted_at: `2026-10-21T12:00:0${index}Z`,
    session_id: "11111111-1111-4111-8111-111111111111",
    action_index: index,
    previous_action_hash: "0".repeat(64),
    action_hash: "ab".repeat(32),
  };
}

function cookie(value: unknown): string {
  return `${FixtureLog.NAME}=${encodeURIComponent(JSON.stringify(value))}`;
}

describe("FixtureLog", () => {
  it("reads back every action it wrote", () => {
    const entries = [
      action("approve", 0),
      action("edit", 1, "Ser is for identity."),
      action("stop", 2),
    ];
    expect(
      FixtureLog.parse(new FixtureLog(entries).header()).actions(),
    ).toEqual(entries);
  });

  it("treats a broken percent-escape as an empty log", () => {
    expect(() => FixtureLog.parse(`${FixtureLog.NAME}=%`)).not.toThrow();
    expect(FixtureLog.parse(`${FixtureLog.NAME}=%`).actions()).toEqual([]);
    expect(FixtureLog.parse(`${FixtureLog.NAME}=%ZZ`).actions()).toEqual([]);
    expect(
      FixtureLog.parse(
        `theme=dark; ${FixtureLog.NAME}=%E0%A4%A; other=1`,
      ).actions(),
    ).toEqual([]);
  });

  it("treats JSON that is not an action list as an empty log", () => {
    expect(FixtureLog.parse(`${FixtureLog.NAME}=%7B%7D`).actions()).toEqual([]);
    expect(FixtureLog.parse(cookie({ actions: [] })).actions()).toEqual([]);
    expect(FixtureLog.parse(`${FixtureLog.NAME}=%25`).actions()).toEqual([]);
  });

  it("drops the chain when any entry is not a tutor action", () => {
    const kept = action("stop", 1);
    const header = cookie([
      { ...action("approve", 0), action: "unknown" },
      kept,
    ]);
    expect(FixtureLog.parse(header).actions()).toEqual([]);
  });

  it("drops an entry the session page cannot render", () => {
    expect(
      FixtureLog.parse(
        cookie([{ ...action("approve", 0), acted_at: "yesterday" }]),
      ).actions(),
    ).toEqual([]);
    expect(FixtureLog.parse(cookie([null])).actions()).toEqual([]);
    expect(
      FixtureLog.parse(
        cookie([
          { ...action("edit", 0, "kept"), edited_output: { text: "x" } },
        ]),
      ).actions(),
    ).toEqual([]);
  });
});
