import { useEffect, useState } from "react";

import { LiveTurnEvents } from "~/lib/live-turn-events";

const KINDS = ["prompt", "gate", "halt", "skipped", "draft", "action"] as const;

/**
 * Follows one session's event stream. Frames arrive on the BFF route, so
 * the browser never opens FastAPI. A dropped connection is EventSource's
 * own reconnect; ids already applied are not painted again.
 */
export function LiveTurnFeed({ sessionId }: { sessionId: string }) {
  const [lines, setLines] = useState<{ id: string; text: string }[]>([]);

  useEffect(() => {
    const feed = new LiveTurnEvents();
    const source = new EventSource(`/sessions/${sessionId}/events`);
    const onEvent = (event: MessageEvent) => {
      const text = feed.accept(String(event.data));
      if (text === null) {
        return;
      }
      const id = event.lastEventId || text;
      setLines((current) =>
        current.some((line) => line.id === id)
          ? current
          : [...current, { id, text }],
      );
    };
    for (const kind of KINDS) {
      source.addEventListener(kind, onEvent);
    }
    return () => {
      source.close();
    };
  }, [sessionId]);

  const halted = lines.some((line) => line.text.includes("checked and fired"));
  const drafted = lines.some((line) => line.text.includes("draft updated"));

  return (
    <section aria-labelledby="live-turn-events" className="space-y-2">
      <h2 id="live-turn-events" className="text-lg font-medium">
        Live turn events
      </h2>
      <div role="log" aria-label="Live turn events">
        <ul className="space-y-1">
          {lines.map((line) => (
            <li key={line.id}>{line.text}</li>
          ))}
        </ul>
      </div>
      {halted && !drafted ? <p>Halted. The stream is quiet.</p> : null}
    </section>
  );
}
