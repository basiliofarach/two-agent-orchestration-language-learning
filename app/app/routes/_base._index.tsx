import type { Route } from "./+types/_base._index";

export function meta(_: Route.MetaArgs) {
  return [{ title: "Tutor dashboard" }];
}

export default function Index() {
  return (
    <p className="text-muted-foreground">
      No sessions yet. Tutor screens arrive in phase 8.
    </p>
  );
}
