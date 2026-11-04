import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import {
  SIMULATION_BANNER,
  SimulationBanner,
} from "~/components/simulation-banner";

afterEach(() => {
  cleanup();
});

it("states that the campaign has no real learner or tutor", () => {
  render(<SimulationBanner />);
  const notice = screen.getByRole("status");
  expect(notice.textContent).toBe(SIMULATION_BANNER);
  expect(notice.querySelector("button")).toBeNull();
});
