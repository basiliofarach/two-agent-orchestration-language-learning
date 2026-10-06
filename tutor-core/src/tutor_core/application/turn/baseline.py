"""Summarise a session's sealed records into its drift norm (REQ-GATES)."""

from statistics import fmean

from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.models.session_baseline import SessionBaseline


class SessionBaselineCalculator:
    """Counts and means over the earlier turns of one session.

    Only records the model wrote a draft for set the support and length
    norms; a halted turn has neither. Every record counts toward the
    flagged prompts, because a refused or stopped prompt is exactly the
    attempt a repeated pattern is made of.
    """

    def baseline(self, records: tuple[TurnAuditRecord, ...]) -> SessionBaseline:
        """Return the norm the next turn of this session is compared with."""
        drafts = tuple(
            record
            for record in records
            if record.output_before_checks is not None
            and record.source_support is not None
        )
        return SessionBaseline(
            prior_turns=len(records),
            generated_turns=len(drafts),
            mean_support_ratio=self._mean(
                tuple(
                    record.source_support.support_ratio
                    for record in drafts
                    if record.source_support is not None
                )
            ),
            mean_output_characters=self._mean(
                tuple(
                    float(len(record.output_before_checks))
                    for record in drafts
                    if record.output_before_checks is not None
                )
            ),
            flagged_prompts=sum(1 for record in records if self._flagged(record)),
        )

    def _mean(self, values: tuple[float, ...]) -> float | None:
        return fmean(values) if values else None

    def _flagged(self, record: TurnAuditRecord) -> bool:
        flags = record.prompt_safety_flags or ()
        return any(flag.severity == "high" for flag in flags)
