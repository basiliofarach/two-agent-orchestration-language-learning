import { CompositionRoot } from "~/.server/composition-root";
import { SimulationRunDetail } from "~/components/simulation-report";
import type { Route } from "./+types/_base.simulation.$runId";

export function meta(_: Route.MetaArgs) {
  return [{ title: "Simulation run" }];
}

export async function loader({ params }: Route.LoaderArgs) {
  return {
    report: await new CompositionRoot(process.env).simulationReport(
      params.runId,
    ),
  };
}

export default function SimulationRun({ loaderData }: Route.ComponentProps) {
  return <SimulationRunDetail report={loaderData.report} />;
}
