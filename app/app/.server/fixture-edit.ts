import { ActionRejected } from "~/.server/action-rejected";
import type { ActionCommand } from "~/.server/tutor-api.types";

type Step = { category: string; source: string };

type SafetyRule = {
  source: string;
  severity: "medium" | "high";
  message: string;
};

/**
 * Fixture copy of `PrepareAction`.
 *
 * An edit is wording the learner would see, so personal data is removed and
 * a high-severity safety flag refuses the edit before the cookie is sealed.
 * The steps are `StandardPiiSteps` and `MinorSafetyRules`. A medium flag,
 * such as a proficiency remark, is recorded and does not refuse the edit.
 */
export class FixtureEditBoundary {
  private readonly redactor = new FixtureRedactor();
  private readonly safety = new FixtureSafety();

  release(command: ActionCommand): ActionCommand {
    const edited = command.editedOutput;
    if (edited === null) {
      return command;
    }
    const redacted = this.redactor.redact(edited);
    const reasons = this.safety.high(redacted);
    if (reasons.length > 0) {
      throw new ActionRejected(
        `the edited reply cannot be released: ${reasons.join(" ")}`,
      );
    }
    return { ...command, editedOutput: redacted };
  }
}

/**
 * JavaScript `\b` and `\w` are ASCII. The Python patterns treat letters
 * such as `í` as word characters, so the fixture compiles those escapes
 * as Unicode boundaries before matching.
 */
class FixturePattern {
  compile(source: string, flags: string): RegExp {
    const word = String.raw`[\p{L}\p{N}_]`;
    const boundary = `(?:(?<!${word})(?=${word})|(?<=${word})(?!${word}))`;
    const translated = source
      .replaceAll(String.raw`\b`, boundary)
      .replaceAll(String.raw`\w`, word);
    return new RegExp(translated, flags);
  }
}

class FixtureRedactor {
  private readonly steps: readonly { category: string; pattern: RegExp }[];

  constructor() {
    const patterns = new FixturePattern();
    this.steps = new FixturePiiSteps().patterns().map((step) => ({
      category: step.category,
      pattern: patterns.compile(step.source, "dgu"),
    }));
  }

  redact(text: string): string {
    try {
      return this.apply(text);
    } catch (error) {
      throw new ActionRejected("redaction failed closed", { cause: error });
    }
  }

  private apply(text: string): string {
    let current = text;
    for (const step of this.steps) {
      step.pattern.lastIndex = 0;
      current = this.rewrite(current, step.pattern, step.category);
    }
    return current;
  }

  private rewrite(text: string, pattern: RegExp, category: string): string {
    const token = `[REDACTED:${category}]`;
    let cursor = 0;
    let out = "";
    for (const match of text.matchAll(pattern)) {
      const whole = match[0];
      const start = match.index;
      if (whole.length === 0) {
        throw new Error("redaction matched empty text");
      }
      out += text.slice(cursor, start);
      out += this.replacement(whole, match, start, token);
      cursor = start + whole.length;
    }
    return out + text.slice(cursor);
  }

  private replacement(
    whole: string,
    match: RegExpMatchArray,
    start: number,
    token: string,
  ): string {
    if (match.groups?.pii === undefined) {
      return token;
    }
    const group = match.indices?.groups?.pii;
    if (group === undefined) {
      throw new Error("pii group has no index");
    }
    return (
      whole.slice(0, group[0] - start) + token + whole.slice(group[1] - start)
    );
  }
}

class FixturePiiSteps {
  private static readonly UPPER = "A-ZÀ-ÖØ-Þ";
  private static readonly LOWER = "a-zß-öø-ÿ";
  private static readonly PARTICLES =
    String.raw`(?:(?:de|del|da|das|di|do|dos|du|la|las|los|le|van|von|der|den)\s+)`;

  patterns(): readonly Step[] {
    return [
      { category: "email", source: this.email() },
      { category: "phone", source: this.phone() },
      { category: "person_name", source: this.personName() },
      { category: "person_name", source: this.lowercasePersonName() },
      { category: "postal_address", source: this.address() },
    ];
  }

  private email(): string {
    return String.raw`[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}`;
  }

  private phone(): string {
    return (
      String.raw`(?<!\w)\+\d{1,3}(?:[\s.\-]\d{2,4}){2,}(?!\w)` +
      String.raw`|(?<!\w)\(\d{2,4}\)\s?\d{3}[\s.\-]?\d{3,4}(?!\w)` +
      String.raw`|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{3,4}\b` +
      String.raw`|\b\d{2,3}(?:[\s.\-]\d{2,3}){3}\b` +
      String.raw`|\b\d{9,15}\b`
    );
  }

  private personName(): string {
    const part =
      `[${FixturePiiSteps.UPPER}](?:['’][${FixturePiiSteps.UPPER}])?[${FixturePiiSteps.LOWER}]+` +
      `(?:[${FixturePiiSteps.UPPER}][${FixturePiiSteps.LOWER}]+)?`;
    const word = `${part}(?:-${part})*`;
    const leadIn = String.raw`(?i:\b(?:my\s+name\s+is|my\s+name['’]s|i['’]m|i\s+am|call\s+me|me\s+llamo|mi\s+nombre\s+es|soy)\s+)`;
    const rest = String.raw`(?:\s+${FixturePiiSteps.PARTICLES}{0,2}${word}){0,3}`;
    return String.raw`${leadIn}(?<pii>${word}${rest})\b`;
  }

  private lowercasePersonName(): string {
    const word = `[${FixturePiiSteps.LOWER}]+(?:['’-][${FixturePiiSteps.LOWER}]+)*`;
    const leadIn = String.raw`(?i:\b(?:my\s+name\s+is|my\s+name['’]s|me\s+llamo|mi\s+nombre\s+es)\s+)`;
    const rest = String.raw`(?:\s+${FixturePiiSteps.PARTICLES}{0,2}${word}){0,2}`;
    const clauseEnd = String.raw`(?=\s*(?:$|[.,;:!?)]|(?:and|y|but|pero)\b))`;
    return `${leadIn}(?<pii>${word}${rest})${clauseEnd}`;
  }

  private address(): string {
    const word = `[${FixturePiiSteps.UPPER}][${FixturePiiSteps.LOWER}]+`;
    const joiner = String.raw`(?:(?:de|del|la|las|los|el)\s+)?`;
    const english = String.raw`\b\d{1,5}\s+(?:${word}\s+){1,4}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd)\b\.?`;
    const spanish = String.raw`\b(?:[Cc]alle|C/|[Aa]venida|Avda\.?|[Pp]laza|[Pp]aseo)\s*${joiner}${word}(?:\s+${joiner}${word})*,?\s*(?:n[º°o]\.?\s*)?\d{1,5}\b`;
    return `${english}|${spanish}`;
  }
}

class FixtureSafety {
  private static readonly RULES: readonly SafetyRule[] = [
    {
      source: "search the (web|internet)|look (it |this )?up online",
      severity: "high",
      message: "This asks for the open web, which this tutor cannot use.",
    },
    {
      source: String.raw`\bdiagnos(e|is)\b|\bprescription\b`,
      severity: "high",
      message: "This asks for medical advice a language tutor does not give.",
    },
    {
      source: String.raw`\byour level is\b|\btheir level is\b`,
      severity: "medium",
      message: "This talks about an assessed proficiency level.",
    },
    {
      source:
        "ignore (all |any )?(previous|prior) instructions|reveal your (system )?prompt",
      severity: "high",
      message: "This tries to change the tutor's instructions.",
    },
  ];

  private readonly rules: readonly { pattern: RegExp; message: string }[];

  constructor() {
    const patterns = new FixturePattern();
    this.rules = FixtureSafety.RULES.filter(
      (rule) => rule.severity === "high",
    ).map((rule) => ({
      pattern: patterns.compile(rule.source, "iu"),
      message: rule.message,
    }));
  }

  high(text: string): string[] {
    return this.rules
      .filter((rule) => rule.pattern.test(text))
      .map((rule) => rule.message);
  }
}
