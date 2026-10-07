import { Info, OctagonAlert, TriangleAlert } from "lucide-react";

import { Panel, PanelNote } from "~/components/panel";
import { Badge } from "~/components/ui/badge";
import type { Severity, TurnView } from "~/lib/view-models";

const ICONS = {
  low: Info,
  medium: TriangleAlert,
  high: OctagonAlert,
} satisfies Record<Severity, typeof Info>;

const VARIANTS = {
  low: "outline",
  medium: "secondary",
  high: "destructive",
} as const satisfies Record<Severity, string>;

/** Read-only. Unsupported spans are marked in the draft, not only here. */
export function SafetyFlagPanel({
  flags,
  support,
}: Pick<TurnView, "flags" | "support">) {
  return (
    <Panel title="Safety flags">
      <FlagList flags={flags} />
      {support === null ? (
        <PanelNote>Source support was not checked.</PanelNote>
      ) : (
        <p>Support ratio {support.ratio.toFixed(2)}</p>
      )}
    </Panel>
  );
}

function FlagList({ flags }: Pick<TurnView, "flags">) {
  if (flags === null) {
    return <PanelNote>Checks did not run.</PanelNote>;
  }
  if (flags.length === 0) {
    return <PanelNote>No safety flags.</PanelNote>;
  }
  return (
    <ul className="space-y-3">
      {flags.map((flag) => {
        const Icon = ICONS[flag.severity];
        return (
          <li key={`${flag.category}-${flag.message}`}>
            <p className="flex items-center gap-2">
              <Badge variant={VARIANTS[flag.severity]}>
                <Icon aria-hidden="true" />
                Severity {flag.severity}
              </Badge>
              <code>{flag.category}</code>
            </p>
            <p className="mt-1">{flag.message}</p>
          </li>
        );
      })}
    </ul>
  );
}
