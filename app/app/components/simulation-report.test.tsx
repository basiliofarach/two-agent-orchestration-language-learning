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

it("names a pending licence on the list and omits a confirmed one", () => {
  render(
    <MemoryRouter>
      <SimulationRunList
        runs={[
          {
            run_id: "sim-pending",
            dataset_version: "sim-dataset/unreleased",
            tier: "1",
            finished_at: null,
            label: "simulated:unreleased",
            passed_invariants: false,
            licence_status: "pending",
            complete: false,
          },
          {
            run_id: "sim-confirmed",
            dataset_version: "sim-dataset/1.0.0",
            tier: "1",
            finished_at: "2026-11-04T12:00:00Z",
            label: "simulated:sim-dataset/1.0.0",
            passed_invariants: true,
            licence_status: "confirmed",
            complete: true,
          },
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: /sim-pending/ }).textContent).toMatch(
    /licence review pending/,
  );
  expect(
    screen.getByRole("link", { name: /sim-confirmed/ }).textContent,
  ).not.toMatch(/licence/i);
});

it("shows no licence line when the review is confirmed", () => {
  render(
    <SimulationRunDetail
      report={{
        run_id: "sim-2",
        dataset_version: "sim-dataset/1.0.0",
        label: "simulated:sim-dataset/1.0.0",
        licence_status: "confirmed",
        pending_sources: [],
        rates: [],
        invariants: [],
        finished: true,
      }}
    />,
  );
  expect(screen.queryByText(/Licence/)).toBeNull();
});
