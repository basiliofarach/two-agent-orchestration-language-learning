import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpTutorApi } from "~/.server/tutor-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: Response) {
  const fetch = vi.fn(async (_url: URL) => response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("HttpTutorApi", () => {
  it("keeps the base path prefix", async () => {
    const fetch = stubFetch(Response.json([]));
    await new HttpTutorApi("http://api.test/v1").sessions();
    expect(fetch.mock.calls[0]?.[0].href).toBe("http://api.test/v1/sessions");
  });

  it("encodes an id so it cannot climb to another endpoint", async () => {
    const fetch = stubFetch(Response.json({}));
    await new HttpTutorApi("http://api.test/").audit("../turns/x");
    expect(fetch.mock.calls[0]?.[0].href).toBe(
      "http://api.test/sessions/..%2Fturns%2Fx/audit",
    );
  });

  it("throws the backend status as a response", async () => {
    stubFetch(new Response(null, { status: 404, statusText: "Not Found" }));
    await expect(
      new HttpTutorApi("http://api.test").turn("missing"),
    ).rejects.toMatchObject({ status: 404 });
  });
});
