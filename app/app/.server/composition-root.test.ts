import { expect, it } from "vitest";

import { CompositionRoot } from "~/.server/composition-root";

it("reports prototype unless the process is in simulation mode", async () => {
  const prototype = await new CompositionRoot({
    TUTOR_API_MODE: "fixture",
  }).health();
  const simulation = await new CompositionRoot({
    TUTOR_API_MODE: "fixture",
    TUTOR_MODE: "simulation",
  }).health();
  expect(prototype.mode).toBe("prototype");
  expect(simulation.mode).toBe("simulation");
});
