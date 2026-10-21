import { createHash } from "node:crypto";

import type { HumanActionJson, TutorAction } from "~/.server/tutor-api.types";

/**
 * Tutor actions recorded while the dashboard is on the fixture backend.
 *
 * The cookie is the fixture's stand-in for the audit table: each request
 * builds a new API, and the browser sends back what the last action stored.
 * Live mode does not use it; FastAPI is the record.
 *
 * The browser supplies the cookie. A value that cannot be decoded, is not
 * a JSON array, or holds an entry that is not a tutor action is an empty
 * log: one bad cookie must not 500 a loader or crash the session page.
 * Entries are one chain, so a single bad entry drops the whole cookie.
 */
export class FixtureLog {
  static readonly NAME = "tutor_fixture_log";

  /**
   * Browsers drop a cookie over 4096 bytes without telling the server, which
   * would lose an action the tutor saw accepted. Refuse it instead.
   */
  static readonly MAX_HEADER_BYTES = 4000;

  static empty(): FixtureLog {
    return new FixtureLog([]);
  }

  static from(request: Request): FixtureLog {
    return FixtureLog.parse(request.headers.get("cookie"));
  }

  /** `Set-Cookie` header value, or the `Cookie` header a test builds. */
  static parse(header: string | null): FixtureLog {
    const encoded = FixtureLog.encoded(header);
    if (encoded === null) {
      return FixtureLog.empty();
    }
    const entries = FixtureLog.read(encoded);
    if (entries === null) {
      return FixtureLog.empty();
    }
    return new FixtureLog(entries);
  }

  constructor(private readonly entries: HumanActionJson[]) {}

  actions(): HumanActionJson[] {
    return this.entries;
  }

  append(action: HumanActionJson): FixtureLog {
    return new FixtureLog([...this.entries, action]);
  }

  fits(): boolean {
    return Buffer.byteLength(this.header()) <= FixtureLog.MAX_HEADER_BYTES;
  }

  header(): string {
    const value = encodeURIComponent(JSON.stringify(this.entries));
    return `${FixtureLog.NAME}=${value}; Path=/; HttpOnly; SameSite=Lax`;
  }

  private static encoded(header: string | null): string | null {
    if (header === null || header === "") {
      return null;
    }
    const match = header
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${FixtureLog.NAME}=`));
    if (match === undefined) {
      return null;
    }
    return match.slice(FixtureLog.NAME.length + 1);
  }

  /**
   * `null` means the cookie is not a log. `decodeURIComponent` throws
   * `URIError` on a broken percent-escape; that is the same outcome as
   * JSON that does not parse.
   */
  private static read(encoded: string): HumanActionJson[] | null {
    let parsed: unknown;
    try {
      parsed = JSON.parse(decodeURIComponent(encoded));
    } catch {
      return null;
    }
    if (!Array.isArray(parsed)) {
      return null;
    }
    const entries: HumanActionJson[] = [];
    for (const item of parsed) {
      const entry = FixtureLog.entry(item);
      if (entry === null) {
        return null;
      }
      entries.push(entry);
    }
    return entries;
  }

  private static entry(value: unknown): HumanActionJson | null {
    const row = FixtureLog.row(value);
    if (row === null) {
      return null;
    }
    const action = FixtureLog.actionName(row.action);
    const edited = FixtureLog.textOrNull(row.edited_output);
    const sessionId = FixtureLog.textOrNull(row.session_id);
    const previous = FixtureLog.textOrNull(row.previous_action_hash);
    const hash = FixtureLog.textOrNull(row.action_hash);
    const index = FixtureLog.indexOrNull(row.action_index);
    if (
      action === null ||
      edited === undefined ||
      sessionId === undefined ||
      previous === undefined ||
      hash === undefined ||
      index === undefined
    ) {
      return null;
    }
    const turnId = row.turn_id;
    const tutorId = row.tutor_id;
    const actedAt = row.acted_at;
    if (typeof turnId !== "string" || turnId.length === 0) {
      return null;
    }
    if (typeof tutorId !== "string" || tutorId.length === 0) {
      return null;
    }
    if (!FixtureLog.isInstant(actedAt)) {
      return null;
    }
    if (!FixtureLog.editAgrees(action, edited)) {
      return null;
    }
    return {
      turn_id: turnId,
      tutor_id: tutorId,
      action,
      edited_output: edited,
      acted_at: actedAt,
      session_id: sessionId,
      action_index: index,
      previous_action_hash: previous,
      action_hash: hash,
    };
  }

  private static row(value: unknown): Record<string, unknown> | null {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return null;
    }
    return value as Record<string, unknown>;
  }

  private static actionName(value: unknown): TutorAction | null {
    if (
      value === "approve" ||
      value === "edit" ||
      value === "override" ||
      value === "stop"
    ) {
      return value;
    }
    return null;
  }

  /** `undefined` means the field is neither a string nor JSON `null`. */
  private static textOrNull(value: unknown): string | null | undefined {
    if (value === null) {
      return null;
    }
    if (typeof value !== "string") {
      return undefined;
    }
    return value;
  }

  private static indexOrNull(value: unknown): number | null | undefined {
    if (value === null) {
      return null;
    }
    if (typeof value !== "number" || !Number.isInteger(value)) {
      return undefined;
    }
    return value;
  }

  private static isInstant(value: unknown): value is string {
    return (
      typeof value === "string" && !Number.isNaN(new Date(value).getTime())
    );
  }

  private static editAgrees(
    action: TutorAction,
    edited: string | null,
  ): boolean {
    if (action === "edit") {
      return edited !== null && edited.trim().length > 0;
    }
    return edited === null;
  }
}

/** Stable digests for fixture chain fields. Not the production hasher. */
export class FixtureDigest {
  hash(value: string): string {
    return createHash("sha256").update(value).digest("hex");
  }
}
