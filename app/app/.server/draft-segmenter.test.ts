import { describe, expect, it } from "vitest";

import { DraftSegmenter } from "~/.server/draft-segmenter";
import type { SourceSupportJson, SpanJson } from "~/.server/tutor-api.types";
import type { DraftSegment } from "~/lib/view-models";

const segmenter = new DraftSegmenter();
const noCitations = new Map<string, number>();

describe("DraftSegmenter", () => {
  it("keeps an unsupported claim inside the draft and numbers the supported one", () => {
    const draft = "Supported claim. Unsupported claim.";
    const segments = segmenter.segment(
      draft,
      support(
        [span(draft, "Supported claim.", ["chunk-1"])],
        [span(draft, "Unsupported claim.")],
      ),
      new Map([["chunk-1", 1]]),
    );
    expect(segments).toEqual([
      {
        kind: "supported",
        start: 0,
        text: "Supported claim.",
        citations: ["1"],
      },
      { kind: "plain", start: 16, text: " " },
      { kind: "unsupported", start: 17, text: "Unsupported claim." },
    ]);
    expect(joined(segments)).toBe(draft);
  });

  it("shows an overlapping claim as unsupported, never as supported", () => {
    const draft = "One claim here.";
    const whole = span(draft, draft, ["chunk-1"]);
    const segments = segmenter.segment(
      draft,
      support([whole], [{ ...whole, source_ids: [] }]),
      noCitations,
    );
    expect(segments.map((segment) => segment.kind)).toEqual(["unsupported"]);
    expect(joined(segments)).toBe(draft);
  });

  it("clamps spans that run past the draft and drops empty ones", () => {
    const draft = "Short.";
    const segments = segmenter.segment(
      draft,
      support(
        [{ text: "", start: 3, end: 3, source_ids: ["chunk-1"] }],
        [{ text: "", start: -4, end: 99, source_ids: [] }],
      ),
      noCitations,
    );
    expect(segments).toEqual([
      { kind: "unsupported", start: 0, text: "Short." },
    ]);
  });

  it("returns the whole draft as plain text when support was not checked", () => {
    expect(segmenter.segment("A refusal.", null, noCitations)).toEqual([
      { kind: "plain", start: 0, text: "A refusal." },
    ]);
  });

  it("keeps the chunk id of a source the context panel does not list", () => {
    const draft = "Cited elsewhere.";
    const [segment] = segmenter.segment(
      draft,
      support([span(draft, draft, ["chunk-9"])], []),
      noCitations,
    );
    expect(segment).toMatchObject({
      kind: "supported",
      citations: ["chunk-9"],
    });
  });
});

function span(draft: string, text: string, sourceIds: string[] = []): SpanJson {
  const start = draft.indexOf(text);
  return { text, start, end: start + text.length, source_ids: sourceIds };
}

function support(
  supported: SpanJson[],
  unsupported: SpanJson[],
): SourceSupportJson {
  return { supported, unsupported, support_ratio: 0.5 };
}

function joined(segments: DraftSegment[]): string {
  return segments.map((segment) => segment.text).join("");
}
