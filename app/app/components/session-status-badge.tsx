import { Badge } from "~/components/ui/badge";

export function SessionStatusBadge({ open }: { open: boolean }) {
  return (
    <Badge variant={open ? "secondary" : "outline"}>
      {open ? "Open" : "Stopped"}
    </Badge>
  );
}
