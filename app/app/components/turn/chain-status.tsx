import { Ban, Check } from "lucide-react";

import type { ChainBreak } from "~/lib/view-models";

/** The hash chain as the verifier reported it, in words as well as an icon. */
export function ChainStatus({ chainBreak }: { chainBreak: ChainBreak | null }) {
  if (chainBreak === null) {
    return (
      <p className="flex items-center gap-2">
        <Check aria-hidden="true" className="size-4" />
        Chain verified: intact
      </p>
    );
  }
  const index =
    chainBreak.actionIndex === null
      ? ""
      : ` Action chain index ${chainBreak.actionIndex}.`;
  return (
    <p className="flex items-center gap-2">
      <Ban aria-hidden="true" className="size-4" />
      Chain verified: broken ({chainBreak.reason}).{index}
    </p>
  );
}
