import type {
  HumanActionJson,
  TurnRecordJson,
} from "~/.server/tutor-api.types";
import type { AuditFieldView } from "~/lib/view-models";

const REQUIRED = [
  "learner_prompt",
  "retrieved_context_ids",
  "model_revision",
  "decoding_params",
  "output_before_checks",
  "output_after_checks",
  "safety_flags",
  "policy_version",
  "previous_record_hash",
  "record_hash",
] as const satisfies readonly (keyof TurnRecordJson)[];

/**
 * Every REQ-AUDIT field, in the order an examiner reads them.
 * A key the record does not carry is a rendering error: the page fails
 * instead of showing a shorter list.
 */
export class AuditFields {
  constructor(
    private readonly record: TurnRecordJson,
    private readonly actions: HumanActionJson[] | undefined,
  ) {}

  rows(): AuditFieldView[] {
    for (const key of REQUIRED) {
      if (!(key in this.record)) {
        throw new Error(`Audit record is missing ${key}.`);
      }
    }
    if (this.actions === undefined) {
      throw new Error("Audit record is missing human actions.");
    }
    this.presentHash("previous_record_hash");
    this.presentHash("record_hash");
    if (!this.record.policy_version) {
      throw new Error("Audit record is missing policy_version.");
    }
    return [
      { label: "Redacted learner prompt", value: this.prompt() },
      { label: "Redacted categories", value: this.categories() },
      {
        label: "Retrieved context identifiers",
        value: this.identifiers(),
      },
      { label: "Model revision", value: this.revision() },
      { label: "Decoding parameters", value: this.decoding() },
      {
        label: "Output before checks",
        value: this.text(this.record.output_before_checks),
      },
      {
        label: "Output after checks",
        value: this.text(this.record.output_after_checks),
      },
      { label: "Safety flags", value: this.flags() },
      { label: "Human action", value: this.humanAction() },
      { label: "Policy version", value: this.record.policy_version },
      {
        label: "Previous record hash",
        value: this.record.previous_record_hash,
      },
      { label: "Record hash", value: this.record.record_hash },
    ];
  }

  private presentHash(key: "previous_record_hash" | "record_hash"): void {
    const value = this.record[key];
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`Audit record is missing ${key}.`);
    }
  }

  private prompt(): string {
    const text = this.record.learner_prompt?.text;
    if (typeof text !== "string") {
      throw new Error("Audit record is missing learner_prompt.");
    }
    return text.length === 0 ? "(empty)" : text;
  }

  private categories(): string {
    const categories = this.record.learner_prompt?.redacted_categories;
    if (!Array.isArray(categories)) {
      throw new Error("Audit record is missing learner_prompt.");
    }
    return categories.length === 0 ? "None" : categories.join(", ");
  }

  private identifiers(): string {
    const ids = this.record.retrieved_context_ids;
    return ids.length === 0 ? "None" : ids.join(", ");
  }

  private revision(): string {
    return this.record.model_revision ?? "Not recorded";
  }

  private decoding(): string {
    const params = this.record.decoding_params;
    if (params === null) {
      return "Not recorded";
    }
    return `temperature ${params.temperature}, top_p ${params.top_p}, max tokens ${params.max_tokens}`;
  }

  private text(value: string | null): string {
    return value === null ? "Not recorded" : value;
  }

  private flags(): string {
    const flags = this.record.safety_flags;
    if (flags === null) {
      return "Not recorded";
    }
    if (flags.length === 0) {
      return "None";
    }
    return flags
      .map((flag) => `${flag.severity} ${flag.category}: ${flag.message}`)
      .join("\n");
  }

  private humanAction(): string {
    const actions = this.actions ?? [];
    if (actions.length === 0) {
      return "None recorded";
    }
    return actions
      .map((action) => {
        const edited =
          action.edited_output === null ? "" : `: ${action.edited_output}`;
        return `${action.action} by ${action.tutor_id} at ${action.acted_at}${edited}`;
      })
      .join("\n");
  }
}
