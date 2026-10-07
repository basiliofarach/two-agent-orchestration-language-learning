import { Badge } from "~/components/ui/badge";
import type { DraftSegment } from "~/lib/view-models";

/**
 * The draft as the tutor reviews it. Unsupported claims are marked in place;
 * supported ones carry the number of the source they rest on.
 */
export function DraftText({ segments }: { segments: DraftSegment[] }) {
  return (
    <p className="leading-relaxed">
      {segments.map((segment) => (
        <Segment key={segment.start} segment={segment} />
      ))}
    </p>
  );
}

function Segment({ segment }: { segment: DraftSegment }) {
  if (segment.kind === "unsupported") {
    return (
      <>
        <mark className="bg-destructive/10 text-inherit underline decoration-destructive decoration-wavy underline-offset-4">
          {segment.text}
        </mark>{" "}
        <Badge variant="destructive" className="align-middle">
          Unsupported
        </Badge>
      </>
    );
  }
  if (segment.kind === "supported" && segment.citations.length > 0) {
    return (
      <span>
        {segment.text}
        <sup className="ms-0.5 text-muted-foreground">
          <span className="sr-only">Source </span>
          {segment.citations.join(", ")}
        </sup>
      </span>
    );
  }
  return <span>{segment.text}</span>;
}
