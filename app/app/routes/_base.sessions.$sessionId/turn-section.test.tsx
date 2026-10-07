import { cleanup, render, screen } from "@testing-library/react";
import { createRoutesStub } from "react-router";
import { afterEach, expect, it } from "vitest";

import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";
import { TurnSection } from "./turn-section";

afterEach(() => {
  cleanup();
});

it("keeps every panel labelled when a session has several turns", async () => {
  const projection = new TurnProjection(new DraftSegmenter());
  const api = new FixtureTutorApi();
  const turns = await Promise.all(
    [FixtureTutorApi.turnIds.completed, FixtureTutorApi.turnIds.halted].map(
      async (turnId) => {
        const detail = await api.turn(turnId);
        return projection.project(detail.record, detail.cited);
      },
    ),
  );
  const Stub = createRoutesStub([
    {
      path: "/",
      Component: () =>
        turns.map((turn) => <TurnSection key={turn.turnId} turn={turn} />),
    },
  ]);
  render(<Stub />);

  const drafts = await screen.findAllByRole("region", {
    name: "Generated draft",
  });
  expect(drafts).toHaveLength(2);
  expect(drafts[1]?.textContent).toContain("Not reached.");
  expect(screen.getAllByRole("region", { name: "Turn 1" })).toHaveLength(2);
});
