import { ActionRejected } from "~/.server/action-rejected";
import type {
  ActionCommand,
  AuditJson,
  RecordedActionJson,
  RecordedActionResult,
  SessionSummaryJson,
  TurnDetailJson,
} from "~/.server/tutor-api.types";

/**
 * The FastAPI endpoints the dashboard uses. `HttpTutorApi` calls the
 * backend; `FixtureTutorApi` serves recorded turns for development and tests.
 *
 * A missing resource is thrown as a 404 `Response`, so a loader renders the
 * route's error boundary either way. The browser never calls these URLs.
 */
export abstract class TutorApi {
  abstract sessions(): Promise<SessionSummaryJson[]>;
  abstract session(sessionId: string): Promise<SessionSummaryJson>;
  abstract audit(sessionId: string): Promise<AuditJson>;
  abstract turn(turnId: string): Promise<TurnDetailJson>;
  abstract recordAction(command: ActionCommand): Promise<RecordedActionResult>;
  abstract events(sessionId: string, after: string | null): Promise<string>;
}

export class HttpTutorApi extends TutorApi {
  private readonly baseUrl: URL;

  constructor(baseUrl: string) {
    super();
    // The trailing slash keeps a path prefix such as `/api` when paths resolve.
    this.baseUrl = new URL(baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  }

  sessions(): Promise<SessionSummaryJson[]> {
    return this.get(["sessions"]);
  }

  session(sessionId: string): Promise<SessionSummaryJson> {
    return this.get(["sessions", sessionId]);
  }

  audit(sessionId: string): Promise<AuditJson> {
    return this.get(["sessions", sessionId, "audit"]);
  }

  turn(turnId: string): Promise<TurnDetailJson> {
    return this.get(["turns", turnId]);
  }

  async recordAction(command: ActionCommand): Promise<RecordedActionResult> {
    const body: { tutor_id: string; action: string; edited_output?: string } = {
      tutor_id: command.tutorId,
      action: command.action,
    };
    if (command.action === "edit") {
      body.edited_output = command.editedOutput ?? "";
    }
    const recorded = await this.post<RecordedActionJson>(
      ["sessions", command.sessionId, "turns", command.turnId, "actions"],
      body,
    );
    return { action: recorded.action, setCookie: null };
  }

  async events(sessionId: string, after: string | null): Promise<string> {
    const headers = new Headers();
    if (after !== null && after !== "") {
      headers.set("Last-Event-ID", after);
    }
    const response = await fetch(this.url(["sessions", sessionId, "events"]), {
      headers,
    });
    if (!response.ok) {
      throw new Response(response.statusText, { status: response.status });
    }
    return response.text();
  }

  private async get<T>(segments: string[]): Promise<T> {
    const response = await fetch(this.url(segments));
    if (!response.ok) {
      throw new Response(response.statusText, { status: response.status });
    }
    return (await response.json()) as T;
  }

  private async post<T>(segments: string[], body: unknown): Promise<T> {
    const response = await fetch(this.url(segments), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.ok) {
      return (await response.json()) as T;
    }
    if (response.status === 409 || response.status === 422) {
      const problem = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;
      const detail =
        problem !== null && typeof problem.detail === "string"
          ? problem.detail
          : response.statusText;
      throw new ActionRejected(detail);
    }
    throw new Response(response.statusText, { status: response.status });
  }

  private url(segments: string[]): URL {
    const path = segments.map((segment) => encodeURIComponent(segment));
    return new URL(path.join("/"), this.baseUrl);
  }
}
