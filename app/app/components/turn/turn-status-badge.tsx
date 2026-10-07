import { Badge } from "~/components/ui/badge";
import type { TurnStatusLabel } from "~/lib/view-models";

const VARIANTS = {
  Refused: "destructive",
  "Held for review": "secondary",
  "Awaiting tutor approval": "outline",
} as const satisfies Record<TurnStatusLabel, string>;

export function TurnStatusBadge({ label }: { label: TurnStatusLabel }) {
  return <Badge variant={VARIANTS[label]}>{label}</Badge>;
}
