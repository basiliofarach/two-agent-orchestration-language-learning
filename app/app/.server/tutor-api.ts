import type {
  AuditJson,
  SessionSummaryJson,
  TurnDetailJson,
} from "~/.server/tutor-api.types";

/**
 * The FastAPI read endpoints the dashboard uses. `HttpTutorApi` calls the
 * backend; `FixtureTutorApi` serves recorded turns for development and tests.
 *
 * A missing resource is thrown as a 404 `Response`, so a loader renders the
 * route's error boundary either way.
 */
export abstract class TutorApi {
  abstract sessions(): Promise<SessionSummaryJson[]>;
  abstract session(sessionId: string): Promise<SessionSummaryJson>;
  abstract audit(sessionId: string): Promise<AuditJson>;
  abstract turn(turnId: string): Promise<TurnDetailJson>;
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

  private async get<T>(segments: string[]): Promise<T> {
    const path = segments.map((segment) => encodeURIComponent(segment));
    const response = await fetch(new URL(path.join("/"), this.baseUrl));
    if (!response.ok) {
      throw new Response(response.statusText, { status: response.status });
    }
    return (await response.json()) as T;
  }
}
