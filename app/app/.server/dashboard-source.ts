import type { TurnProjection } from "~/.server/turn-projection";
import type { TutorApi } from "~/.server/tutor-api";
import type { AuditJson, SessionSummaryJson } from "~/.server/tutor-api.types";
import type {
  AuditScreen,
  ChainBreak,
  SessionListItem,
  SessionScreen,
} from "~/lib/view-models";

/** What each dashboard loader returns. Loaders are the only callers. */
export class DashboardSource {
  constructor(
    private readonly api: TutorApi,
    private readonly projection: TurnProjection,
  ) {}

  async sessions(): Promise<SessionListItem[]> {
    const sessions = await this.api.sessions();
    return sessions.map((session) => this.listItem(session));
  }

  async session(sessionId: string): Promise<SessionScreen> {
    const [summary, audit] = await Promise.all([
      this.api.session(sessionId),
      this.api.audit(sessionId),
    ]);
    // The audit view carries records but not what each cited; the turn
    // endpoint does. Fetch them together, not one after another.
    const details = await Promise.all(
      audit.records.map((record) => this.api.turn(record.turn_id)),
    );
    return {
      ...this.listItem(summary),
      turns: details.map((detail) =>
        this.projection.project(detail.record, detail.cited),
      ),
      chainBreak: this.chainBreak(audit),
    };
  }

  async auditTurn(turnId: string): Promise<AuditScreen> {
    const detail = await this.api.turn(turnId);
    return {
      turn: this.projection.project(detail.record, detail.cited),
      recordIntact: detail.record_intact,
    };
  }

  private listItem(session: SessionSummaryJson): SessionListItem {
    return {
      sessionId: session.session_id,
      learnerId: session.learner_id,
      open: session.open,
      startedAt: session.started_at,
    };
  }

  private chainBreak(audit: AuditJson): ChainBreak | null {
    if (audit.intact) {
      return null;
    }
    // tutor-core names the turn and the reason on every break. Guessing
    // either would misreport the record a tutor is asked to trust.
    if (audit.break_turn_id === null || audit.break_reason === null) {
      throw new Error("The audit view reports a break without naming it.");
    }
    return { turnId: audit.break_turn_id, reason: audit.break_reason };
  }
}
