import { Panel, PanelNote } from "~/components/panel";
import { Badge } from "~/components/ui/badge";
import type { TurnView } from "~/lib/view-models";

export function ContextPanel({ context }: Pick<TurnView, "context">) {
  return (
    <Panel title="Retrieved context">
      <ContextBody context={context} />
    </Panel>
  );
}

function ContextBody({ context }: Pick<TurnView, "context">) {
  if (context === null) {
    return <PanelNote>Not reached.</PanelNote>;
  }
  if (context.length === 0) {
    return <PanelNote>No snippets were retrieved.</PanelNote>;
  }
  return (
    <ol className="space-y-4">
      {context.map((snippet) => (
        <li key={snippet.chunkId} className="border-s-2 ps-3">
          <p className="font-medium">Source {snippet.citation}</p>
          <p className="mt-1">{snippet.content}</p>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-muted-foreground">
            <code>{snippet.sourceUri}</code>
            <span>Version {snippet.version}</span>
            <Badge variant="outline">
              Review status {snippet.reviewStatus}
            </Badge>
          </p>
        </li>
      ))}
    </ol>
  );
}
