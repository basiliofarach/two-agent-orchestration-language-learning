import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";

import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import {
  SimulationRunDetail,
  SimulationRunList,
} from "~/components/simulation-report";

afterEach(() => {
  cleanup();
});

it("lists an unfinished run and shows k/n rather than a score", async () => {
  const api = new FixtureTutorApi();
  const runs = await api.simulationRuns();
  const report = await api.simulationReport("sim-1");
  render(
    <MemoryRouter>
      <SimulationRunList runs={runs} />
      <SimulationRunDetail report={report} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: /sim-1/ })).toBeTruthy();
  expect(
    screen.getByText("Licence review pending: grammar-profile"),
  ).toBeTruthy();
  expect(screen.getByText("1/2")).toBeTruthy();
  expect(screen.getByText("pass")).toBeTruthy();
});
