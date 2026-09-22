"""Capability ports as ABCs (DEC-0001)."""

from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.source_support import SourceSupportPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)

__all__ = [
    "AuditSinkPort",
    "CipherPort",
    "ClockPort",
    "EmbeddingPort",
    "GrammarCheckPort",
    "KnowledgeBasePort",
    "LanguageModelPort",
    "LearnerHistoryPort",
    "OversightGatePort",
    "PiiRedactionPort",
    "PolicyArtifactPort",
    "PromptTemplatePort",
    "SafetyClassifierPort",
    "SourceSupportPort",
    "TransactionConnection",
    "TransactionalWork",
    "UnitOfWorkPort",
]
