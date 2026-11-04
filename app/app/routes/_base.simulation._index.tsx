import { CompositionRoot } from "~/.server/composition-root";
import { SimulationRunList } from "~/components/simulation-report";
import type { Route } from "./+types/_base.simulation._index";

export function meta(_: Route.MetaArgs) {
  return [{ title: "Simulation" }];
}

export async function loader() {
  return { runs: await new CompositionRoot(process.env).simulationRuns() };
}

export default function SimulationIndex({ loaderData }: Route.ComponentProps) {
  return <SimulationRunList runs={loaderData.runs} />;
}
