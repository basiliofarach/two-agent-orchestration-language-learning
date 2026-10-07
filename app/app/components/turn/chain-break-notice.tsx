import { ShieldAlert } from "lucide-react";

import type { ChainBreak, ChainBreakReason } from "~/lib/view-models";

const EXPLANATIONS = {
  tampered: "The stored record no longer matches its digest.",
  excised: "The record before it is missing from the chain.",
  unreadable:
    "The record could not be read, so this session's turns cannot be shown.",
} satisfies Record<ChainBreakReason, string>;

/** The audit chain no longer verifies (REQ-AUDIT). Shown above the turns. */
export function ChainBreakNotice({ chainBreak }: { chainBreak: ChainBreak }) {
  return (
    <div
      role="alert"
      className="flex gap-3 rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-destructive"
    >
      <ShieldAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
      <div>
        <p className="font-medium">
          The audit chain breaks at turn record {chainBreak.turnId}.
        </p>
        <p>{EXPLANATIONS[chainBreak.reason]}</p>
      </div>
    </div>
  );
}
