"""Pydantic models. Audit and evidence types are frozen (DEC-0002, DEC-0010)."""

from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.models.corpus import CorpusDocument, IngestedDocument
from tutor_core.domain.models.learner import (
    HistoryItem,
    LearnerHistorySnapshot,
    LearnerId,
)
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
    Snippet,
    SourceRef,
)
from tutor_core.domain.models.safety import (
    ClaimSpan,
    DecodingParams,
    GeneratedUnit,
    GrammarFinding,
    ModelCompletion,
    RedactedText,
    RenderedPrompt,
    SafetyFlag,
    SourceSupportReport,
    StoredLearnerPrompt,
)
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateDecision, GateStage, GateVerdict

__all__ = [
    "ClaimSpan",
    "CorpusDocument",
    "DecodingParams",
    "GateDecision",
    "GateStage",
    "GateVerdict",
    "GeneratedUnit",
    "GrammarFinding",
    "HistoryItem",
    "HumanAction",
    "IngestedDocument",
    "LearnerHistorySnapshot",
    "LearnerId",
    "ModelCompletion",
    "RedactedRetrievalRequest",
    "RedactedText",
    "RenderedPrompt",
    "RetrievalResult",
    "SafetyFlag",
    "Snippet",
    "SourceRef",
    "SourceSupportReport",
    "StoredLearnerPrompt",
    "TurnAuditRecord",
    "TurnState",
]
