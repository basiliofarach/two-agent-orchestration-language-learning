import { Link } from "react-router";

import type {
  SimulationReportJson,
  SimulationRunSummaryJson,
} from "~/.server/tutor-api.types";

export function SimulationRunList({
  runs,
}: {
  runs: SimulationRunSummaryJson[];
}) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">Simulation</h1>
      {runs.length === 0 ? (
        <p>No simulation runs have been written yet.</p>
      ) : (
        <ul className="divide-y rounded-xl border">
          {runs.map((run) => (
            <li key={run.run_id}>
              <Link
                to={`/simulation/${run.run_id}`}
                className="block px-4 py-3 outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="font-medium">{run.run_id}</span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {run.label} · tier {run.tier} ·{" "}
                  {run.complete ? "finished" : "incomplete"}
                  {run.licence_status === "pending"
                    ? " · licence review pending"
                    : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SimulationRunDetail({
  report,
}: {
  report: SimulationReportJson;
}) {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-medium">{report.run_id}</h1>
        <p>{report.label}</p>
        {report.licence_status === "pending" ? (
          <p>
            Licence review pending
            {report.pending_sources.length > 0
              ? `: ${report.pending_sources.join(", ")}`
              : ""}
          </p>
        ) : null}
      </header>
      <table>
        <caption className="text-left font-medium">Invariants</caption>
        <thead>
          <tr>
            <th className="pr-4 text-left">Invariant</th>
            <th className="text-left">Result</th>
          </tr>
        </thead>
        <tbody>
          {report.invariants.map((row) => (
            <tr key={row.invariant_id}>
              <td className="pr-4">{row.invariant_id}</td>
              <td>{row.passed ? "pass" : "fail"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table>
        <caption className="text-left font-medium">Rates</caption>
        <thead>
          <tr>
            <th className="pr-4 text-left">Rate</th>
            <th className="text-left">k/n</th>
          </tr>
        </thead>
        <tbody>
          {report.rates.map((row) => (
            <tr key={row.name}>
              <td className="pr-4">{row.name}</td>
              <td>
                {row.k}/{row.n}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
