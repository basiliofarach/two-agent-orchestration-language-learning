import type { SourceSupportJson, SpanJson } from "~/.server/tutor-api.types";
import type { DraftSegment } from "~/lib/view-models";

type Interval = {
  start: number;
  end: number;
  kind: "supported" | "unsupported";
  sourceIds: string[];
};

/**
 * Splits a draft into contiguous segments so unsupported claims stay visible
 * in the text itself, not only in a side list. Where spans overlap, an
 * unsupported span wins: a claim is never shown as supported by mistake.
 */
export class DraftSegmenter {
  segment(
    draft: string,
    support: SourceSupportJson | null,
    citations: ReadonlyMap<string, number>,
  ): DraftSegment[] {
    const intervals = [
      ...(support?.unsupported ?? []).map((span) =>
        this.interval(span, "unsupported", draft.length),
      ),
      ...(support?.supported ?? []).map((span) =>
        this.interval(span, "supported", draft.length),
      ),
    ]
      .filter((interval) => interval.end > interval.start)
      .sort(
        (left, right) =>
          left.start - right.start ||
          Number(right.kind === "unsupported") -
            Number(left.kind === "unsupported"),
      );

    const segments: DraftSegment[] = [];
    let cursor = 0;
    for (const interval of intervals) {
      if (interval.end <= cursor) {
        continue;
      }
      const start = Math.max(interval.start, cursor);
      if (start > cursor) {
        segments.push({
          kind: "plain",
          start: cursor,
          text: draft.slice(cursor, start),
        });
      }
      segments.push(this.marked(draft, start, interval, citations));
      cursor = interval.end;
    }
    if (cursor < draft.length) {
      segments.push({
        kind: "plain",
        start: cursor,
        text: draft.slice(cursor),
      });
    }
    return segments;
  }

  private interval(
    span: SpanJson,
    kind: Interval["kind"],
    length: number,
  ): Interval {
    return {
      start: Math.min(Math.max(0, span.start), length),
      end: Math.min(Math.max(0, span.end), length),
      kind,
      sourceIds: span.source_ids,
    };
  }

  private marked(
    draft: string,
    start: number,
    interval: Interval,
    citations: ReadonlyMap<string, number>,
  ): DraftSegment {
    const text = draft.slice(start, interval.end);
    if (interval.kind === "unsupported") {
      return { kind: "unsupported", start, text };
    }
    return {
      kind: "supported",
      start,
      text,
      // A source the context panel does not list keeps its chunk id rather
      // than disappearing from the draft.
      citations: interval.sourceIds.map(
        (sourceId) => citations.get(sourceId)?.toString() ?? sourceId,
      ),
    };
  }
}
