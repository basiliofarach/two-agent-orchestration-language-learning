import { createHash } from "node:crypto";

import type { HumanActionJson } from "~/.server/tutor-api.types";

/**
 * Tutor actions recorded while the dashboard is on the fixture backend.
 *
 * The cookie is the fixture's stand-in for the audit table: each request
 * builds a new API, and the browser sends back what the last action stored.
 * Live mode does not use it; FastAPI is the record.
 */
export class FixtureLog {
  static readonly NAME = "tutor_fixture_log";

  static empty(): FixtureLog {
    return new FixtureLog([]);
  }

  static from(request: Request): FixtureLog {
    return FixtureLog.parse(request.headers.get("cookie"));
  }

  /** `Set-Cookie` header value, or the `Cookie` header a test builds. */
  static parse(header: string | null): FixtureLog {
    if (header === null || header === "") {
      return FixtureLog.empty();
    }
    const pairs = header.split(";").map((part) => part.trim());
    const match = pairs.find((part) => part.startsWith(`${FixtureLog.NAME}=`));
    if (match === undefined) {
      return FixtureLog.empty();
    }
    const raw = decodeURIComponent(match.slice(FixtureLog.NAME.length + 1));
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return FixtureLog.empty();
      }
      return new FixtureLog(parsed as HumanActionJson[]);
    } catch {
      return FixtureLog.empty();
    }
  }

  constructor(private readonly entries: HumanActionJson[]) {}

  actions(): HumanActionJson[] {
    return this.entries;
  }

  append(action: HumanActionJson): FixtureLog {
    return new FixtureLog([...this.entries, action]);
  }

  header(): string {
    const value = encodeURIComponent(JSON.stringify(this.entries));
    return `${FixtureLog.NAME}=${value}; Path=/; HttpOnly; SameSite=Lax`;
  }
}

/** Stable digests for fixture chain fields. Not the production hasher. */
export class FixtureDigest {
  hash(value: string): string {
    return createHash("sha256").update(value).digest("hex");
  }
}
