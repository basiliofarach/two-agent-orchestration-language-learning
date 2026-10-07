import { Ban, Check, Minus } from "lucide-react";

import { Panel } from "~/components/panel";
import { Badge } from "~/components/ui/badge";
import type { GateState, TurnView } from "~/lib/view-models";

const ICONS = {
  passed: Check,
  fired: Ban,
  not_reached: Minus,
} satisfies Record<GateState, typeof Check>;

const VARIANTS = {
  passed: "secondary",
  fired: "destructive",
  not_reached: "outline",
} as const satisfies Record<GateState, string>;

/** The four gates in graph order, each checked-and-passed, fired, or not reached. */
export function GateTimeline({
  gates,
  policyVersion,
}: Pick<TurnView, "gates" | "policyVersion">) {
  return (
    <Panel
      title="Gate timeline"
      action={<Badge variant="outline">Policy version {policyVersion}</Badge>}
    >
      <ol className="space-y-4">
        {gates.map((gate) => {
          const Icon = ICONS[gate.state];
          return (
            <li key={gate.name} className="border-s-2 ps-3">
              <p className="flex flex-wrap items-center gap-2 font-medium">
                <Icon aria-hidden="true" className="size-4" />
                {gate.label}
                <Badge variant={VARIANTS[gate.state]}>{gate.stateText}</Badge>
              </p>
              <p className="mt-1">{gate.reason}</p>
              <p className="text-muted-foreground">
                Policy rule <code>{gate.policyRuleId}</code>
              </p>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}
