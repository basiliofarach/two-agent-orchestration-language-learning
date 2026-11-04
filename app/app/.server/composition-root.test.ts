import { afterEach, describe, expect, it, vi } from "vitest";

import { CompositionRoot } from "~/.server/composition-root";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CompositionRoot", () => {
  it("serves the fixture sessions when no mode is set", async () => {
    const sessions = await new CompositionRoot({}).dashboardSource().sessions();
    expect(sessions.map((session) => session.sessionId)).toEqual(
      Object.values(FixtureTutorApi.sessionIds),
    );
  });

  it("reads FastAPI at TUTOR_API_URL in live mode", async () => {
    const fetch = vi.fn(async (_url: URL) => Response.json([]));
    vi.stubGlobal("fetch", fetch);
    await new CompositionRoot({
      TUTOR_API_MODE: "live",
      TUTOR_API_URL: "http://api.test:9000",
    })
      .dashboardSource()
      .sessions();
    expect(fetch.mock.calls[0]?.[0].href).toBe("http://api.test:9000/sessions");
  });

  it("rejects an unknown mode instead of falling back to fixtures", () => {
    const root = new CompositionRoot({ TUTOR_API_MODE: "liev" });
    expect(() => root.dashboardSource()).toThrow('not "liev"');
  });

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
});
