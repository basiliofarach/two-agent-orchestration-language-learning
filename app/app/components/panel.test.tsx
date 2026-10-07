import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { Panel } from "~/components/panel";

afterEach(() => {
  cleanup();
});

it("labels each panel by its own heading when the same panel renders twice", () => {
  render(
    <>
      <Panel title="Generated draft">First</Panel>
      <Panel title="Generated draft">Second</Panel>
    </>,
  );
  const regions = screen.getAllByRole("region", { name: "Generated draft" });
  expect(regions.map((region) => region.textContent)).toEqual([
    "Generated draftFirst",
    "Generated draftSecond",
  ]);
  const ids = screen
    .getAllByRole("heading", { name: "Generated draft" })
    .map((heading) => heading.id);
  expect(new Set(ids).size).toBe(2);
});

it("renders the heading at the requested level", () => {
  render(
    <Panel title="Gate timeline" level={2}>
      Body
    </Panel>,
  );
  expect(
    screen.getByRole("heading", { level: 2, name: "Gate timeline" }),
  ).toBeTruthy();
});
