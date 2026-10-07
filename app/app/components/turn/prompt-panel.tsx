import { Panel } from "~/components/panel";
import { Badge } from "~/components/ui/badge";
import type { TurnView } from "~/lib/view-models";

export function PromptPanel({ prompt }: Pick<TurnView, "prompt">) {
  return (
    <Panel title="Learner prompt">
      <p>{prompt.text}</p>
      {prompt.redactedCategories.length === 0 ? (
        <p className="text-muted-foreground">No redacted categories.</p>
      ) : (
        <p className="flex flex-wrap items-center gap-2">
          Redacted categories:
          {prompt.redactedCategories.map((category) => (
            <Badge key={category} variant="outline">
              {category}
            </Badge>
          ))}
        </p>
      )}
    </Panel>
  );
}
