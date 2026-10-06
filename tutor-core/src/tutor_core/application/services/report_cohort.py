"""Read the cohort counts for the periodic non-discrimination review."""

from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.models.cohort import CohortReport
from tutor_core.domain.ports.cohort_report import CohortReportPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class CohortCommand(BaseModel):
    """The reviewer asked for the counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CohortReceipt(BaseModel):
    """Filled inside the read transaction."""

    model_config = ConfigDict(extra="forbid")

    report: CohortReport | None = None


class CohortWork(TransactionalWork):
    """Aggregate on the enlisted connection. No write."""

    def __init__(self, receipt: CohortReceipt, cohort: CohortReportPort) -> None:
        self._receipt = receipt
        self._cohort = cohort

    async def run(self, connection: TransactionConnection) -> None:
        """Store the counts."""
        self._receipt.report = await self._cohort.report()


class PrepareCohort(PrepareHandler[CohortCommand, CohortCommand]):
    """No fields to check."""

    def run(self, command: CohortCommand) -> CohortCommand:
        """Return the command."""
        return command


class ExecuteCohort(ExecuteHandler[CohortCommand, CohortReport]):
    """Read inside the unit of work so the connection closes (DEC-0014)."""

    def __init__(self, unit: UnitOfWorkPort, cohort: CohortReportPort) -> None:
        self._unit = unit
        self._cohort = cohort

    async def run(self, prepared: CohortCommand) -> CohortReport:
        """Return the counts."""
        receipt = CohortReceipt()
        await self._unit.run(CohortWork(receipt, self._cohort))
        if receipt.report is None:
            msg = "the cohort counts were not read"
            raise ValueError(msg)
        return receipt.report


class FinaliseCohort(FinaliseHandler[CohortReport, CohortReport]):
    """The counts are the result. No verdict is added."""

    def run(self, executed: CohortReport) -> CohortReport:
        """Return the counts."""
        return executed


class ReportCohort(
    ApplicationService[CohortCommand, CohortCommand, CohortReport, CohortReport]
):
    """The container key for the cohort report. Adds no method (DEC-0011)."""
