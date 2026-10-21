import {
  Check,
  CircleDashed,
  FileText,
  type LucideIcon,
  MessageSquare,
  ShieldAlert,
  UserCheck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRevalidator } from "react-router";

import { Panel, PanelNote } from "~/components/panel";
import {
  type LiveKind,
  type LiveLine,
  LiveTurnEvents,
  LiveTurnSummary,
} from "~/lib/live-turn-events";
import type { ActionView, TurnView } from "~/lib/view-models";

const KINDS = ["prompt", "gate", "halt", "skipped", "draft", "action"] as const;

const ICONS: Record<LiveKind, { icon: LucideIcon; className: string }> = {
  prompt: { icon: MessageSquare, className: "text-muted-foreground" },
  gate: { icon: Check, className: "text-muted-foreground" },
  halt: { icon: ShieldAlert, className: "text-destructive-text" },
  skipped: { icon: CircleDashed, className: "text-muted-foreground" },
  draft: { icon: FileText, className: "text-muted-foreground" },
  action: { icon: UserCheck, className: "text-foreground" },
};

/**
 * Follows one session's event stream. Frames arrive on the BFF route, so
 * the browser never opens FastAPI. A dropped connection is EventSource's
 * own reconnect; ids already applied are not painted again.
 *
 * When the stream names a turn or an action the panels above do not show,
 * the route revalidates once, so the tutor never reviews a stale turn.
 */
export function LiveTurnFeed({
  sessionId,
  turns,
  actions,
}: {
  sessionId: string;
  turns: TurnView[];
  actions: ActionView[];
}) {
  const [lines, setLines] = useState<LiveLine[]>([]);
  const revalidator = useRevalidator();
  const revalidatedAt = useRef(0);

  useEffect(() => {
    const feed = new LiveTurnEvents();
    const source = new EventSource(`/sessions/${sessionId}/events`);
    const onEvent = (event: MessageEvent) => {
      const line = feed.accept(String(event.data));
      if (line === null) {
        return;
      }
      setLines((current) =>
        current.some((item) => item.id === line.id)
          ? current
          : [...current, line],
      );
    };
    for (const kind of KINDS) {
      source.addEventListener(kind, onEvent);
    }
    return () => {
      source.close();
    };
  }, [sessionId]);

  const summary = useMemo(() => new LiveTurnSummary(lines), [lines]);
  const loadedTurnIds = useMemo(
    () => turns.map((turn) => turn.turnId),
    [turns],
  );
  const loadedActions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const action of actions) {
      counts.set(action.turnId, (counts.get(action.turnId) ?? 0) + 1);
    }
    return counts;
  }, [actions]);

  useEffect(() => {
    if (
      revalidator.state === "idle" &&
      lines.length > revalidatedAt.current &&
      summary.behind(loadedTurnIds, loadedActions)
    ) {
      revalidatedAt.current = lines.length;
      void revalidator.revalidate();
    }
  }, [lines, summary, loadedTurnIds, loadedActions, revalidator]);

  return (
    <Panel title="Live turn events" level={2}>
      <div role="log" aria-label="Live turn events">
        {lines.length === 0 ? (
          <PanelNote>Waiting for the session's event stream.</PanelNote>
        ) : (
          <ol className="space-y-1.5 text-sm">
            {lines.map((line) => {
              const { icon: Icon, className } = ICONS[line.kind];
              return (
                <li key={line.id} className="flex gap-2">
                  <Icon
                    aria-hidden="true"
                    className={`mt-0.5 size-4 shrink-0 ${className}`}
                  />
                  <span>{line.text}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
      {summary.latestHalted() ? (
        <PanelNote>Halted. The stream is quiet.</PanelNote>
      ) : null}
    </Panel>
  );
}
