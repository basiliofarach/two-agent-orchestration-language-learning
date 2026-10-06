"""Cohort counts over the audit log. The query does not decide anything."""

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_core.domain.models.cohort import CohortCount, CohortReport
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class CohortAggregation(BaseRepository):
    """Count gate decisions and refusals (REQ-MINOR, REQ-HISTORY).

    The statements are selects. The result is a :class:`CohortReport`, which
    has counts and no verdict: the periodic review is a person's job
    (ARCHITECTURE §10).
    """

    _DECISIONS = """
        SELECT decision, count(*)
        FROM gate_evaluation
        GROUP BY decision
        ORDER BY decision
        """

    _TURNS = """
        SELECT
            count(*),
            count(*) FILTER (WHERE refused IS TRUE)
        FROM turn_audit
        """

    def __init__(self, connection: TransactionConnection) -> None:
        super().__init__(connection)

    async def report(self) -> CohortReport:
        """Return the counts. Do not classify a cohort as biased or fair."""
        decisions = await self._fetch_all(self._DECISIONS, {})
        totals = await self._fetch_one(self._TURNS, {})
        turns = 0 if totals is None else int(str(totals[0]))
        refusals = 0 if totals is None else int(str(totals[1]))
        return CohortReport(
            by_decision=tuple(
                CohortCount(decision=str(row[0]), rows=int(str(row[1])))
                for row in decisions
            ),
            refusals=refusals,
            turns=turns,
        )
