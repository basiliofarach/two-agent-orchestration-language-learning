import { describe, expect, it } from "vitest";

import { AuditFields } from "~/.server/audit-fields";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import type { TurnRecordJson } from "~/.server/tutor-api.types";

const LABELS = [
  "Redacted learner prompt",
  "Redacted categories",
  "Retrieved context identifiers",
  "Model revision",
  "Decoding parameters",
  "Output before checks",
  "Output after checks",
  "Safety flags",
  "Human action",
  "Policy version",
  "Previous record hash",
  "Record hash",
];

describe("AuditFields", () => {
  it("renders every REQ-AUDIT field, including a stage the model did not reach", async () => {
    const detail = await new FixtureTutorApi().turn(
      FixtureTutorApi.turnIds.halted,
    );
    const rows = new AuditFields(detail.record, detail.actions).rows();
    expect(rows.map((row) => row.label)).toEqual(LABELS);
    expect(rows.find((row) => row.label === "Model revision")?.value).toBe(
      "Not recorded",
    );
    expect(rows.find((row) => row.label === "Human action")?.value).toBe(
      "None recorded",
    );
    expect(rows.find((row) => row.label === "Policy version")?.value).toBe(
      "policy-1",
    );
  });

  it("throws when a required field is absent", async () => {
    const detail = await new FixtureTutorApi().turn(
      FixtureTutorApi.turnIds.completed,
    );
    const record = { ...detail.record };
    delete (record as Partial<TurnRecordJson>).model_revision;
    expect(() => new AuditFields(record, []).rows()).toThrow(
      "missing model_revision",
    );
  });

  it("throws when the human-action list was not loaded", async () => {
    const detail = await new FixtureTutorApi().turn(
      FixtureTutorApi.turnIds.completed,
    );
    expect(() => new AuditFields(detail.record, undefined).rows()).toThrow(
      "missing human actions",
    );
  });
});
