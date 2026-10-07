import { type ReactNode, useId } from "react";

import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";

/**
 * A titled, labelled region. The heading id comes from `useId`, so a page can
 * render the same panel once per turn without duplicate ids.
 */
export function Panel({
  title,
  action,
  level = 3,
  className,
  children,
}: {
  title: ReactNode;
  action?: ReactNode;
  level?: 2 | 3;
  className?: string;
  children: ReactNode;
}) {
  const headingId = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={headingId} className={className}>
      <Card className="h-full">
        <CardHeader>
          <CardTitle>
            <Heading id={headingId}>{title}</Heading>
          </CardTitle>
          {action ? <CardAction>{action}</CardAction> : null}
        </CardHeader>
        <CardContent className="space-y-3">{children}</CardContent>
      </Card>
    </section>
  );
}

/** A panel's empty or not-reached state. */
export function PanelNote({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground">{children}</p>;
}
