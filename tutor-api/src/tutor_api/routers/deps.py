"""Every type a route may receive, as one ``Depends()`` alias each.

The first project kept its injection seam in one ``deps.py``; this is that
module. Each alias is the transparent assignment DEC-0013 allows:
``Annotated[T, Depends(Provide(T))]``. A PEP 695 ``type`` alias is not used,
because FastAPI does not unwrap it and would read the parameter as request
data.

What is listed is a use case or configuration, never a repository. The
first project handed routes a ``RepositoryContainer``; here a route holds no
logic and reaches storage only through a service (DEC-0011), so no port or
adapter has an alias. A route that needs a new dependency adds its alias
here, and ``container.py`` registers the provider behind it.

This module and the routers beside it are the only places ``Depends()`` is
imported (rule 3).
"""

from typing import Annotated

from fastapi import Depends

from tutor_api.di.dependency import Provide
from tutor_api.settings import ApplicationSettings
from tutor_core.application.services.conduct_turn import ConductTurn
from tutor_core.application.services.read_audit import ReadAudit, ReadTurn
from tutor_core.application.services.record_human_action import RecordHumanAction
from tutor_core.application.services.replay_turn import ReplayTurn
from tutor_core.application.services.report_cohort import ReportCohort
from tutor_core.application.services.session_surface import (
    ListLearners,
    ListSessions,
    OpenSession,
    ReadSession,
    StreamSession,
)

Settings = Annotated[ApplicationSettings, Depends(Provide(ApplicationSettings))]
Turns = Annotated[ConductTurn, Depends(Provide(ConductTurn))]
TurnReads = Annotated[ReadTurn, Depends(Provide(ReadTurn))]
Replays = Annotated[ReplayTurn, Depends(Provide(ReplayTurn))]
Sessions = Annotated[ListSessions, Depends(Provide(ListSessions))]
SessionReads = Annotated[ReadSession, Depends(Provide(ReadSession))]
Openings = Annotated[OpenSession, Depends(Provide(OpenSession))]
Learners = Annotated[ListLearners, Depends(Provide(ListLearners))]
Audits = Annotated[ReadAudit, Depends(Provide(ReadAudit))]
Actions = Annotated[RecordHumanAction, Depends(Provide(RecordHumanAction))]
Streams = Annotated[StreamSession, Depends(Provide(StreamSession))]
Cohorts = Annotated[ReportCohort, Depends(Provide(ReportCohort))]
