import type {
  HumanActionJson,
  StreamEventJson,
  TurnRecordJson,
} from "~/.server/tutor-api.types";
import type { GateName } from "~/lib/gates";

const GATE_KIND = {
  pass: "gate",
  pause: "halt",
  stop: "halt",
  not_evaluated: "skipped",
} as const;

type Timed = {
  at: string;
  turnIndex: number;
  place: number;
  event: StreamEventJson;
};

/**
 * The fixture's copy of tutor-core `SessionEvents` plus `SseEncoder`.
 * Live mode does not use it: the BFF forwards FastAPI's frames unchanged.
 *
 * A halted turn emits the halt and the gates that were not reached. A draft
 * frame follows only when the record carries `output_after_checks`, the same
 * rule as the backend encoder.
 */
export class SessionEvents {
  static readonly RETRY_MILLISECONDS = 2000;

  encode(
    sessionId: string,
    records: TurnRecordJson[],
    actions: HumanActionJson[],
    after: string | null,
  ): string {
    const events = this.after(this.events(sessionId, records, actions), after);
    const frames = events.map((event) => this.frame(event)).join("");
    return `retry: ${SessionEvents.RETRY_MILLISECONDS}\n\n${frames}`;
  }

  private events(
    sessionId: string,
    records: TurnRecordJson[],
    actions: HumanActionJson[],
  ): StreamEventJson[] {
    const indexes = new Map(
      records.map((record) => [record.turn_id, record.turn_index]),
    );
    const timed: Timed[] = [];
    for (const record of records) {
      timed.push(...this.turn(sessionId, record));
    }
    for (const action of actions) {
      timed.push(
        this.action(sessionId, action, indexes.get(action.turn_id) ?? 0),
      );
    }
    timed.sort((left, right) => {
      if (left.at !== right.at) {
        return left.at < right.at ? -1 : 1;
      }
      if (left.turnIndex !== right.turnIndex) {
        return left.turnIndex - right.turnIndex;
      }
      return left.place - right.place;
    });
    return timed.map((item) => item.event);
  }

  /**
   * Events after `cursor`. An id this stream cannot place replays everything,
   * which is the EventSource contract for an unknown Last-Event-ID.
   */
  private after(
    events: StreamEventJson[],
    cursor: string | null,
  ): StreamEventJson[] {
    if (cursor === null || cursor === "") {
      return events;
    }
    const index = events.findIndex((event) => event.event_id === cursor);
    if (index === -1) {
      return events;
    }
    return events.slice(index + 1);
  }

  private turn(sessionId: string, record: TurnRecordJson): Timed[] {
    const prompt = this.event(record, {
      event_id: `${record.turn_id}:prompt`,
      kind: "prompt",
      session_id: sessionId,
      text: record.learner_prompt.text,
    });
    const timed: Timed[] = [
      {
        at: record.recorded_at,
        turnIndex: record.turn_index,
        place: 0,
        event: prompt,
      },
    ];
    record.gate_evaluations.forEach((gate, index) => {
      timed.push({
        at: record.recorded_at,
        turnIndex: record.turn_index,
        place: index + 1,
        event: this.event(record, {
          event_id: `${record.turn_id}:${gate.gate_name}`,
          kind: GATE_KIND[gate.decision],
          session_id: sessionId,
          gate_name: gate.gate_name,
          decision: gate.decision,
          reason: gate.reason,
          policy_rule_id: gate.policy_rule_id,
        }),
      });
    });
    if (record.output_after_checks !== null) {
      timed.push({
        at: record.recorded_at,
        turnIndex: record.turn_index,
        place: record.gate_evaluations.length + 1,
        event: this.event(record, {
          event_id: `${record.turn_id}:draft`,
          kind: "draft",
          session_id: sessionId,
          text: record.output_after_checks,
        }),
      });
    }
    return timed;
  }

  private action(
    sessionId: string,
    action: HumanActionJson,
    turnIndex: number,
  ): Timed {
    const position =
      action.action_index === null
        ? action.acted_at
        : String(action.action_index);
    return {
      at: action.acted_at,
      turnIndex,
      place: 0,
      event: {
        event_id: `${action.turn_id}:action:${position}`,
        kind: "action",
        turn_id: action.turn_id,
        session_id: sessionId,
        turn_index: turnIndex,
        gate_name: null,
        decision: null,
        reason: null,
        policy_rule_id: null,
        action: action.action,
        text: action.edited_output,
      },
    };
  }

  private event(
    record: TurnRecordJson,
    fields: Partial<StreamEventJson> &
      Pick<StreamEventJson, "event_id" | "kind" | "session_id">,
  ): StreamEventJson {
    return {
      event_id: fields.event_id,
      kind: fields.kind,
      turn_id: record.turn_id,
      session_id: fields.session_id,
      turn_index: record.turn_index,
      gate_name: (fields.gate_name as GateName | null | undefined) ?? null,
      decision: fields.decision ?? null,
      reason: fields.reason ?? null,
      policy_rule_id: fields.policy_rule_id ?? null,
      action: fields.action ?? null,
      text: fields.text ?? null,
    };
  }

  private frame(event: StreamEventJson): string {
    return `id: ${event.event_id}\nevent: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`;
  }
}
