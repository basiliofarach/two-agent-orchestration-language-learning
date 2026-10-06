"""The pinned revision and the template version are what the audit row stores."""

import psycopg
from tests.integration.test_request_transaction import Wired
from tests.support.runtime_pin import RuntimePin
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn

from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class RecordedTurn(TransactionalWork):
    """Read history and append one audit row on the scope's connection."""

    def __init__(
        self,
        history: LearnerHistoryPort,
        sink: AuditSinkPort,
        revision: str,
        template_version: str,
        shared: TransactionConnection,
    ) -> None:
        self._history = history
        self._sink = sink
        self._revision = revision
        self._template_version = template_version
        self._shared = shared
        self.proficiency: str | None = None

    async def run(self, connection: TransactionConnection) -> None:
        assert connection is self._shared
        snapshot = await self._history.read(
            Samples().learner_id(), HistoryFieldSet(fields=("proficiency_level",))
        )
        self.proficiency = snapshot.proficiency_level
        drafted = (
            Samples()
            .audit_record()
            .model_copy(
                update={
                    "model_revision": self._revision,
                    "template_version": self._template_version,
                    "policy_version": "policy-1",
                    "retrieved_context_ids": (),
                }
            )
        )
        sealed = SealedTurn(AuditRecordHash()).at(drafted, AuditRecordHash.GENESIS)
        await self._sink.append(sealed)


class TestPinnedRevisionInTheAuditRecord:
    async def test_revision_and_template_version_match_the_pins(
        self, fresh_database: str
    ) -> None:
        wired = Wired(fresh_database)
        container = wired.container()
        await wired.install(container)
        cipher = container.resolve(CipherPort)
        assert isinstance(cipher, CipherPort)
        with psycopg.connect(fresh_database) as connection:
            connection.execute(
                """
                UPDATE learner
                SET proficiency_level = %s
                WHERE learner_id = %s
                """,
                (cipher.encrypt(b"A2"), Samples().learner_id().value),
            )
        scope = container.scope()
        model = scope.resolve(LanguageModelPort)
        template = scope.resolve(PromptTemplatePort)
        history = scope.resolve(LearnerHistoryPort)
        sink = scope.resolve(AuditSinkPort)
        unit = scope.resolve(UnitOfWorkPort)
        shared = scope.resolve(TransactionConnection)
        assert isinstance(model, LanguageModelPort)
        assert isinstance(template, PromptTemplatePort)
        assert isinstance(history, LearnerHistoryPort)
        assert isinstance(sink, AuditSinkPort)
        assert isinstance(unit, UnitOfWorkPort)
        assert isinstance(shared, TransactionConnection)
        rendered = template.render(
            "explain greetings", Samples().retrieval(), Samples().history()
        )
        assert rendered.template_version == template.template_version()
        assert model.revision() == RuntimePin().weights_sha()
        turn = RecordedTurn(
            history, sink, model.revision(), template.template_version(), shared
        )
        try:
            await unit.run(turn)
        finally:
            engine = container.resolve(DatabaseEngine)
            assert isinstance(engine, DatabaseEngine)
            await engine.dispose()
        assert turn.proficiency == "A2"
        with psycopg.connect(fresh_database) as connection:
            row = connection.execute(
                "SELECT model_revision, template_version FROM turn_audit"
            ).fetchone()
        assert row is not None
        assert row[0] == RuntimePin().weights_sha()
        opened = cipher.decrypt(bytes(row[1])).decode("utf-8")
        assert opened == template.template_version()
