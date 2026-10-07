import { Panel, PanelNote } from "~/components/panel";
import { DraftText } from "~/components/turn/draft-text";
import type { DraftView, TurnView } from "~/lib/view-models";

export function DraftPanel({ draft }: Pick<TurnView, "draft">) {
  return (
    <Panel title="Generated draft">
      {draft === null ? (
        <PanelNote>Not reached.</PanelNote>
      ) : (
        <DraftBody draft={draft} />
      )}
    </Panel>
  );
}

function DraftBody({ draft }: { draft: DraftView }) {
  return (
    <>
      <DraftText segments={draft.segments} />
      {draft.disclosure !== null ? (
        <p className="text-muted-foreground">Disclosure: {draft.disclosure}</p>
      ) : null}
      {draft.beforeChecks !== null ? (
        <details>
          <summary className="cursor-pointer">Output before checks</summary>
          <p className="mt-2">{draft.beforeChecks}</p>
        </details>
      ) : draft.refused ? (
        <PanelNote>
          The model was not called, so there is no output before checks.
        </PanelNote>
      ) : null}
    </>
  );
}
