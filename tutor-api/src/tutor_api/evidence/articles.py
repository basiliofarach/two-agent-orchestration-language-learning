"""The four article files. Each names the requirement and the element it evidences."""

import json

from tutor_api.evidence.body import EvidenceSources, PackBody


class Cited:
    """One requirement and the architectural element that evidences it."""

    def __init__(self, requirement: str, element: str) -> None:
        self._requirement = requirement
        self._element = element

    def text(self) -> str:
        """The citation line."""
        return f"Cites {self._requirement}, architectural element {self._element}."


class JsonBlock:
    """Canonical JSON. Key order is sorted, so two renders match."""

    def __init__(self, value: object) -> None:
        self._value = value

    def text(self) -> str:
        """The JSON text, with a trailing newline."""
        return json.dumps(self._value, indent=2, sort_keys=True) + "\n"


class Article10:
    """Data governance. Documents only; no reviewer name, no learner text."""

    def __init__(self, sources: EvidenceSources, body: PackBody) -> None:
        self._sources = sources
        self._body = body

    def text(self) -> str:
        """Article 10."""
        documents = JsonBlock(
            [item.model_dump(mode="json") for item in self._body.documents]
        )
        return (
            "# Article 10\n\n"
            + Cited(
                "REQ-KB",
                "`kb_document` (source, version, review status) and "
                "`PgVectorKnowledgeBase` (retrieval limited to approved)",
            ).text()
            + "\n"
            + Cited("REQ-HISTORY", "`LearnerHistoryPort` field allowlist").text()
            + "\n"
            + Cited("REQ-MINOR", "`PiiRedactionPort` at the input boundary").text()
            + "\n\n"
            f"Policy version {self._sources.policy_version}. "
            f"Documents: {len(self._body.documents)}. "
            "Reviewer names are not copied.\n\n" + documents.text()
        )


class Article12:
    """Record-keeping. The chain result and the redacted turns."""

    def __init__(self, sources: EvidenceSources, body: PackBody) -> None:
        self._sources = sources
        self._body = body

    def text(self) -> str:
        """Article 12."""
        turns = JsonBlock([item.model_dump(mode="json") for item in self._body.turns])
        unreadable = (
            ", ".join(self._body.unreadable_sessions)
            if self._body.unreadable_sessions
            else "none"
        )
        broken = (
            ", ".join(self._sources.broken_sessions)
            if self._sources.broken_sessions
            else "none"
        )
        return (
            "# Article 12\n\n"
            + Cited(
                "REQ-AUDIT",
                "`TurnAuditRecord`, `previous_record_hash`, `record_hash`",
            ).text()
            + "\n"
            + Cited(
                "REQ-POLICY",
                "`PolicyArtifactPort`, the `policy_version` table, "
                "and `gate_evaluation.policy_rule_id`",
            ).text()
            + "\n\n"
            f"Chain verification: {self._sources.chain_status}. "
            f"Sessions checked: {self._sources.sessions}; "
            f"turns: {self._sources.turns}; "
            f"tutor actions: {self._sources.actions} "
            f"({self._sources.unchained_actions} written before the action "
            "chain existed, listed but not chain-verified). "
            f"Broken sessions: {broken}. "
            f"Unreadable sessions: {unreadable}.\n\n"
            "The check links each record to its predecessor, starting at the "
            "genesis hash. A missing tail is not reported separately from a "
            "shorter chain.\n\n"
            "`evaluated_at` is the timestamp stored on the gate row.\n\n"
            "History snapshots are not copied. Learner-facing text in this "
            "pack has been redacted. Safety-flag messages are omitted; "
            "categories are kept.\n\n" + turns.text()
        )


class Article14:
    """Human oversight. Logged actions. The dashboard UI is not in the pack."""

    def __init__(self, body: PackBody) -> None:
        self._body = body

    def text(self) -> str:
        """Article 14."""
        actions = JsonBlock(
            [item.model_dump(mode="json") for item in self._body.actions]
        )
        return (
            "# Article 14\n\n"
            + Cited(
                "REQ-GATES",
                "`domain/gates/`, four classes, invoked in graph order",
            ).text()
            + "\n"
            + Cited(
                "REQ-DASH",
                "the logged `HumanAction`. The dashboard UI is not in this pack",
            ).text()
            + "\n\n"
            "A sensitivity non-pass ends the graph before drift. A gate that "
            "was not reached is `not_evaluated` on the turn. This pack does "
            "not claim that gate ran.\n\n"
            "`tutor_id` is the identifier the caller sent. The pack does not "
            "prove who was at the keyboard.\n\n" + actions.text()
        )


class Article15:
    """Accuracy. Synthetic scores only. No tutor-sourced comparison."""

    def __init__(self, body: PackBody) -> None:
        self._body = body

    def text(self) -> str:
        """Article 15."""
        return (
            "# Article 15\n\n"
            + Cited(
                "REQ-ACCURACY",
                "`PromptTemplatePort` (`template_version`) and "
                "`SourceSupportReport.unsupported`",
            ).text()
            + "\n"
            + Cited("REQ-EVAL", "`ScenarioCatalogue` and `Rubric`").text()
            + "\n"
            + Cited("REQ-FIELD", "the synthetic rubric, labelled as such").text()
            + "\n\n"
            f"Drift report label: {self._body.rubric_label}. "
            "Tutor-sourced inputs are not in this pack. "
            "No comparison is invented.\n\n"
            "Session drift thresholds are not calibrated here.\n\n" + self._scores()
        )

    def _scores(self) -> str:
        if not self._body.rubric_lines:
            return "Synthetic scores were not supplied to this command.\n"
        return "\n".join(self._body.rubric_lines) + "\n"
