import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpTutorApi } from "~/.server/tutor-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: Response) {
  const fetch = vi.fn(async (_url: URL, _init?: RequestInit) => response);
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

  it("posts an approval without an edited reply", async () => {
    const fetch = stubFetch(
      Response.json({
        action: { action: "approve" },
        stopped: false,
      }),
    );
    await new HttpTutorApi("http://api.test/").recordAction({
      sessionId: "11111111-1111-4111-8111-111111111111",
      turnId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      tutorId: "tutor",
      action: "approve",
      editedOutput: null,
    });
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url.href).toBe(
      "http://api.test/sessions/11111111-1111-4111-8111-111111111111/turns/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/actions",
    );
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(init?.body))).toEqual({
      tutor_id: "tutor",
      action: "approve",
    });
  });

  it("rejects a 409 with the backend's reason", async () => {
    stubFetch(Response.json({ detail: "session is stopped" }, { status: 409 }));
    await expect(
      new HttpTutorApi("http://api.test/").recordAction({
        sessionId: "s",
        turnId: "t",
        tutorId: "tutor",
        action: "stop",
        editedOutput: null,
      }),
    ).rejects.toThrow("session is stopped");
  });

  it("rejects a 422 with the validator message, not the status text", async () => {
    stubFetch(
      Response.json(
        {
          detail: [
            {
              loc: ["body", "edited_output"],
              msg: "Value error, edited_output is required when the tutor edits",
            },
          ],
        },
        { status: 422, statusText: "Unprocessable Entity" },
      ),
    );
    await expect(
      new HttpTutorApi("http://api.test/").recordAction({
        sessionId: "s",
        turnId: "t",
        tutorId: "tutor",
        action: "edit",
        editedOutput: " ",
      }),
    ).rejects.toThrow("edited_output is required when the tutor edits");
  });

  it("forwards Last-Event-ID and returns the event body", async () => {
    const fetch = stubFetch(new Response("retry: 2000\n\n", { status: 200 }));
    const body = await new HttpTutorApi("http://api.test").events(
      "session",
      "cursor-1",
    );
    expect(body).toContain("retry: 2000");
    const [, init] = fetch.mock.calls[0] ?? [];
    const headers = init?.headers;
    expect(headers).toBeInstanceOf(Headers);
    expect(
      headers instanceof Headers ? headers.get("Last-Event-ID") : null,
    ).toBe("cursor-1");
  });
});
