import { cleanup, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { createRoutesStub } from "react-router";
import { afterEach, expect, it } from "vitest";

import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";
import type { ActionView, TurnView } from "~/lib/view-models";
import { TutorControls } from "./tutor-controls";

afterEach(() => {
  cleanup();
});

async function turn(turnId: string): Promise<TurnView> {
  const detail = await new FixtureTutorApi().turn(turnId);
  return new TurnProjection(new DraftSegmenter()).project(
    detail.record,
    detail.cited,
  );
}

function renderControls(
  view: TurnView,
  options: {
    actions?: ActionView[];
    sessionOpen?: boolean;
    actionError?: { action: string; message: string } | null;
  } = {},
) {
  const Stub = createRoutesStub([
    {
      path: "/",
      Component: () => (
        <TutorControls
          turn={view}
          actions={options.actions ?? []}
          sessionOpen={options.sessionOpen ?? true}
          actionError={options.actionError ?? null}
        />
      ),
    },
  ]);
  render(<Stub />);
}

it("starts an edit from the checked draft, not an empty box", async () => {
  const view = await turn(FixtureTutorApi.turnIds.completed);
  renderControls(view);
  const box = await screen.findByLabelText<HTMLTextAreaElement>("Edited reply");
  expect(box.value).toBe(view.draft?.afterChecks);
  expect(box.value).toContain("The verb ser agrees with the subject.");
});

it("puts stop behind a confirmation that says the record is kept", async () => {
  renderControls(await turn(FixtureTutorApi.turnIds.completed));
  const confirm = await screen.findByRole("button", {
    name: "Confirm stop session",
    hidden: true,
  });
  expect(confirm.closest("details")?.open).toBe(false);
  expect(screen.getByText(/Every record is kept/)).toBeTruthy();
});

it("does not offer approve on a halted turn", async () => {
  renderControls(await turn(FixtureTutorApi.turnIds.halted));
  await screen.findByRole("button", { name: "Override" });
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
});

it("reopens the edit after a refused edit and says it was not recorded", async () => {
  renderControls(await turn(FixtureTutorApi.turnIds.completed), {
    actionError: { action: "edit", message: "the edit trips a safety flag" },
  });
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("Not recorded: the edit trips a safety flag");
  expect(screen.getByLabelText("Edited reply").closest("details")?.open).toBe(
    true,
  );
});

it("shows the recorded decision and no further decisions", async () => {
  renderControls(await turn(FixtureTutorApi.turnIds.completed), {
    actions: [
      {
        turnId: FixtureTutorApi.turnIds.completed,
        tutorId: "tutor",
        action: "approve",
        editedOutput: null,
        actedAt: "2026-10-21T12:00:00Z",
      },
    ],
  });
  expect(
    await screen.findByText(/Tutor decision: approve by tutor/),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  expect(
    screen.getByRole("button", { name: "Confirm stop session", hidden: true }),
  ).toBeTruthy();
});

it("keeps the edit box read-only in the server render, until React owns it", async () => {
  const view = await turn(FixtureTutorApi.turnIds.completed);
  const Stub = createRoutesStub([
    {
      path: "/",
      Component: () => (
        <TutorControls
          turn={view}
          actions={[]}
          sessionOpen
          actionError={null}
        />
      ),
    },
  ]);
  const html = renderToString(<Stub />);
  expect(html).toMatch(/<textarea[^>]*readOnly=""/i);
  expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Save edited reply/);
});

it("lets the tutor type once the page is hydrated", async () => {
  renderControls(await turn(FixtureTutorApi.turnIds.completed));
  const box = await screen.findByLabelText<HTMLTextAreaElement>("Edited reply");
  expect(box.readOnly).toBe(false);
  expect(
    screen
      .getByRole("button", { name: "Save edited reply", hidden: true })
      .hasAttribute("disabled"),
  ).toBe(false);
});
