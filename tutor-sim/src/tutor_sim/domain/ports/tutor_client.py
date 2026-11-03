"""The tutor API over HTTP. The harness holds no tutor-api import."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_sim.domain.models.client_call import (
    ActionCall,
    AuditCall,
    DetailCall,
    HealthCall,
    LearnerCall,
    ReplayCall,
    SessionCall,
    TurnCall,
)


class TutorClientPort(ABC):
    """What the dashboard can do. Each method is one HTTP call."""

    @abstractmethod
    def health(self) -> HealthCall:
        """``GET /health``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def learners(self) -> LearnerCall:
        """``GET /learners``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
        """``POST /sessions``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        """``POST /turns``. ``prompt`` is the realised utterance, unchanged."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def detail(self, turn_id: UUID) -> DetailCall:
        """``GET /turns/{id}``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        action: str,
        edited_output: str | None,
    ) -> ActionCall:
        """``POST /sessions/{sid}/turns/{tid}/actions``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def audit(self, session_id: UUID) -> AuditCall:
        """``GET /sessions/{id}/audit``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def replay(self, turn_id: UUID) -> ReplayCall:
        """``POST /turns/{id}/replay``."""
        raise NotImplementedError  # pragma: no cover
