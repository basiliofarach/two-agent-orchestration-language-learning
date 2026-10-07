import { describe, expect, it } from "vitest";

import { RouteParams } from "~/.server/route-params";

describe("RouteParams.uuid", () => {
  it("accepts a UUID", () => {
    const id = "11111111-1111-4111-8111-111111111111";
    expect(
      new RouteParams({ sessionId: id }).uuid("sessionId", "Session"),
    ).toBe(id);
  });

  it.each([undefined, "", "../turns/x", "not-a-uuid"])(
    "answers %j with a 404 response",
    (value) => {
      const params = new RouteParams({ sessionId: value });
      expect(() => params.uuid("sessionId", "Session")).toThrow(
        expect.objectContaining({ status: 404 }),
      );
    },
  );
});
