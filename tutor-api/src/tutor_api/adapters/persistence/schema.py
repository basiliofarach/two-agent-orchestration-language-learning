"""Non-audit tables (BE-05) and the append-only audit tables (BE-06)."""

import re
from collections.abc import Callable

import psycopg

from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec
from tutor_core.domain.ports.cipher import CipherPort


class ApplicationRole:
    """The role granted insert and select on the audit tables.

    Injected, not fixed. ``docker/postgres/init/01-roles.sh`` creates the login
    from ``POSTGRES_APP_USER``; with the name hard-coded, a deployment that
    overrode that variable had the audit privileges granted to a NOLOGIN
    placeholder this migration created, while the login the application
    actually uses received none — a silent loss of the REQ-AUDIT control.
    :class:`~tutor_api.settings.ApplicationSettings` resolves the name from the
    same variable Compose reads.

    The name reaches SQL interpolated, so it is checked against the identifier
    grammar and quoted. ``01-roles.sh`` creates it with ``:"app_user"`` — a
    quoted identifier — so quoting here keeps the two spellings identical for
    a name that is not already lower case.
    """

    _GRAMMAR = re.compile(r"\A[A-Za-z_][A-Za-z0-9_$]{0,62}\Z")

    def __init__(self, name: str) -> None:
        if not self._GRAMMAR.match(name):
            msg = f"POSTGRES_APP_USER is not a usable role name: {name!r}"
            raise ValueError(msg)
        self._name = name

    def identifier(self) -> str:
        """The role as a quoted SQL identifier, for GRANT and CREATE ROLE."""
        return f'"{self._name}"'

    def literal(self) -> str:
        """The role as a quoted SQL string, for the ``pg_roles`` lookup."""
        return f"'{self._name}'"


class InstantColumn:
    """One full-precision ``timestamptz`` column (DEC-0010).

    ``timestamptz(n)`` rounds, and ``timestamp`` without time zone comes back
    naive. Neither spelling can be produced here. A new instant column is
    this helper.
    """

    _NAME = re.compile(r"\A[a-z][a-z0-9_]{0,62}\Z")

    def __init__(self, name: str) -> None:
        if self._NAME.fullmatch(name) is None:
            msg = "an instant column name is a lowercase identifier"
            raise ValueError(msg)
        self._name = name

    def required(self) -> str:
        """The column, always present."""
        return f"{self._name} timestamptz NOT NULL"

    def optional(self) -> str:
        """The column, absent until the event it records has happened."""
        return f"{self._name} timestamptz"


class BaseSchema:
    """Knowledge base, learner, session, and policy tables."""

    def embedding_dimensions(self) -> int:
        return 768

    def statements(self) -> tuple[str, ...]:
        width = self.embedding_dimensions()
        effective_from = InstantColumn("effective_from").required()
        reviewed_at = InstantColumn("reviewed_at").optional()
        retain_until = InstantColumn("retain_until").required()
        occurred_at = InstantColumn("occurred_at").required()
        started_at = InstantColumn("started_at").required()
        stopped_at = InstantColumn("stopped_at").optional()
        return (
            "CREATE EXTENSION IF NOT EXISTS vector",
            f"""
            CREATE TABLE policy_version (
                version text PRIMARY KEY,
                allowed_actions ciphertext NOT NULL,
                denied_actions ciphertext NOT NULL,
                escalation_rules ciphertext NOT NULL,
                article_mappings ciphertext NOT NULL,
                {effective_from}
            )
            """,
            f"""
            CREATE TABLE kb_document (
                id uuid PRIMARY KEY,
                source_uri text NOT NULL,
                version text NOT NULL,
                review_status text NOT NULL,
                reviewed_by ciphertext,
                {reviewed_at},
                CONSTRAINT kb_document_review_status CHECK (
                    review_status IN ('pending', 'approved', 'rejected')
                )
            )
            """,
            f"""
            CREATE TABLE kb_chunk (
                id uuid PRIMARY KEY,
                document_id uuid NOT NULL REFERENCES kb_document (id),
                ordinal integer NOT NULL,
                content ciphertext NOT NULL,
                embedding vector({width}) NOT NULL
            )
            """,
            """
            CREATE INDEX kb_chunk_embedding_hnsw
                ON kb_chunk USING hnsw (embedding vector_cosine_ops)
            """,
            f"""
            CREATE TABLE learner (
                learner_id uuid PRIMARY KEY,
                pseudonym ciphertext NOT NULL,
                proficiency_level ciphertext NOT NULL,
                {retain_until}
            )
            """,
            f"""
            CREATE TABLE learner_history_event (
                id uuid PRIMARY KEY,
                learner_id uuid NOT NULL REFERENCES learner (learner_id),
                item_id ciphertext NOT NULL,
                correct boolean NOT NULL,
                {occurred_at}
            )
            """,
            f"""
            CREATE TABLE tutoring_session (
                id uuid PRIMARY KEY,
                tutor_id ciphertext NOT NULL,
                learner_id uuid NOT NULL REFERENCES learner (learner_id),
                {started_at},
                {stopped_at},
                stop_reason ciphertext
            )
            """,
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        return (
            "DROP TABLE IF EXISTS tutoring_session",
            "DROP TABLE IF EXISTS learner_history_event",
            "DROP TABLE IF EXISTS learner",
            "DROP TABLE IF EXISTS kb_chunk",
            "DROP TABLE IF EXISTS kb_document",
            "DROP TABLE IF EXISTS policy_version",
            "DROP EXTENSION IF EXISTS vector",
        )


class TurnAuditGenerationCheck:
    """Generation columns are null together, or present together."""

    def expression(self) -> str:
        """The boolean both the table definition and the upgrade apply."""
        return """
                        (
                            model_revision IS NULL
                            AND template_version IS NULL
                            AND decoding_params IS NULL
                            AND output_before_checks IS NULL
                            AND output_after_checks IS NULL
                            AND ai_disclosure IS NULL
                            AND refused IS NULL
                            AND safety_flags IS NULL
                            AND source_support IS NULL
                        )
                        OR
                        (
                            model_revision IS NOT NULL
                            AND template_version IS NOT NULL
                            AND decoding_params IS NOT NULL
                            AND output_before_checks IS NOT NULL
                            AND output_after_checks IS NOT NULL
                            AND ai_disclosure IS NOT NULL
                            AND refused IS NOT NULL
                            AND safety_flags IS NOT NULL
                            AND source_support IS NOT NULL
                        )"""


class AuditSchema:
    """Append-only turn, gate, citation, and tutor-action tables (DEC-0006).

    ``turn_audit`` is inserted once. Generation columns are null when the
    model did not run, and they are null together. ``gate_evaluation`` and
    ``turn_citation`` reference that row and commit with it. ``human_action``
    is a later insert; the turn row is never updated to record it.
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        role = self._role.identifier()
        rolname = self._role.literal()
        generation = TurnAuditGenerationCheck().expression()
        recorded_at = InstantColumn("recorded_at").required()
        evaluated_at = InstantColumn("evaluated_at").required()
        acted_at = InstantColumn("acted_at").required()
        return (
            f"""
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = {rolname}
                ) THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END
            $role$
            """,
            f"""
            CREATE TABLE turn_audit (
                turn_id uuid PRIMARY KEY,
                session_id uuid NOT NULL REFERENCES tutoring_session (id),
                turn_index integer NOT NULL,
                learner_prompt_redacted ciphertext NOT NULL,
                redacted_categories ciphertext NOT NULL,
                model_revision text,
                template_version ciphertext,
                decoding_params ciphertext,
                output_before_checks ciphertext,
                output_after_checks ciphertext,
                ai_disclosure ciphertext,
                refused boolean,
                safety_flags ciphertext,
                source_support ciphertext,
                policy_version text NOT NULL REFERENCES policy_version (version),
                previous_record_hash text NOT NULL,
                record_hash text NOT NULL,
                {recorded_at},
                CONSTRAINT turn_audit_session_turn UNIQUE (session_id, turn_index),
                CONSTRAINT turn_audit_generation_together CHECK ({generation}
                )
            )
            """,
            """
            CREATE TABLE turn_citation (
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                chunk_id uuid NOT NULL REFERENCES kb_chunk (id),
                ordinal integer NOT NULL,
                PRIMARY KEY (turn_id, ordinal),
                UNIQUE (turn_id, chunk_id)
            )
            """,
            f"""
            CREATE TABLE gate_evaluation (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                gate_name text NOT NULL,
                decision text NOT NULL,
                reason ciphertext,
                policy_rule_id text NOT NULL,
                {evaluated_at},
                CONSTRAINT gate_evaluation_decision CHECK (
                    decision IN ('pass', 'pause', 'stop', 'not_evaluated')
                ),
                CONSTRAINT gate_evaluation_not_evaluated_reason CHECK (
                    decision <> 'not_evaluated' OR reason IS NOT NULL
                )
            )
            """,
            f"""
            CREATE TABLE human_action (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                tutor_id ciphertext NOT NULL,
                action text NOT NULL,
                edited_output ciphertext,
                {acted_at},
                CONSTRAINT human_action_kind CHECK (
                    action IN ('approve', 'edit', 'override', 'stop')
                ),
                CONSTRAINT human_action_edit_has_output CHECK (
                    action <> 'edit' OR edited_output IS NOT NULL
                )
            )
            """,
            """
            CREATE FUNCTION reject_audit_mutation()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION
                    'append-only: % on % is forbidden', TG_OP, TG_TABLE_NAME;
            END;
            $$
            """,
            """
            CREATE TRIGGER turn_audit_append_only
                BEFORE UPDATE OR DELETE ON turn_audit
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            """
            CREATE TRIGGER gate_evaluation_append_only
                BEFORE UPDATE OR DELETE ON gate_evaluation
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            """
            CREATE TRIGGER turn_citation_append_only
                BEFORE UPDATE OR DELETE ON turn_citation
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            """
            CREATE TRIGGER human_action_append_only
                BEFORE UPDATE OR DELETE ON human_action
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            *self._privileges(role, "turn_audit"),
            *self._privileges(role, "gate_evaluation"),
            *self._privileges(role, "turn_citation"),
            *self._privileges(role, "human_action"),
        )

    def _privileges(self, role: str, table: str) -> tuple[str, ...]:
        return (
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC, {role}",
            f"GRANT INSERT, SELECT ON TABLE {table} TO {role}",
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM {role}",
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        return (
            "DROP TRIGGER IF EXISTS human_action_append_only ON human_action",
            "DROP TRIGGER IF EXISTS turn_citation_append_only ON turn_citation",
            "DROP TRIGGER IF EXISTS gate_evaluation_append_only ON gate_evaluation",
            "DROP TRIGGER IF EXISTS turn_audit_append_only ON turn_audit",
            "DROP FUNCTION IF EXISTS reject_audit_mutation()",
            "DROP TABLE IF EXISTS human_action",
            "DROP TABLE IF EXISTS turn_citation",
            "DROP TABLE IF EXISTS gate_evaluation",
            "DROP TABLE IF EXISTS turn_audit",
        )


class AuditSchemaUpgrade:
    """Move a database stamped at ``46c99fd72506`` onto the current audit shape.

    That revision executes :meth:`AuditSchema.statements` when it runs, so a
    database migrated before citations and tutor actions became their own
    tables still has the old ``turn_audit`` columns, while a later fresh
    install of the same revision already has the new tables. Each step runs
    only when the old shape is still present. Downgrade rebuilds the
    superseded row by inserting into a new table: the append-only trigger
    rejects ``UPDATE`` of ``turn_audit``.
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        role = self._role.identifier()
        generation = TurnAuditGenerationCheck().expression()
        acted_at = InstantColumn("acted_at").required()
        return (
            f"""
            DO $upgrade$
            DECLARE
                required_column text;
            BEGIN
                -- The old columns are referenced only inside these branches.
                -- plpgsql plans a statement when it first runs, so a fresh
                -- catalogue, which never enters, does not look the columns up.
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'turn_audit'
                      AND column_name = 'human_action'
                ) THEN
                    IF EXISTS (
                        SELECT 1 FROM turn_audit WHERE human_action IS NOT NULL
                    ) THEN
                        RAISE EXCEPTION
                            'legacy human_action ciphertext cannot be split';
                    END IF;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'turn_audit'
                      AND column_name = 'retrieved_context_ids'
                ) THEN
                    IF EXISTS (
                        SELECT 1
                        FROM turn_audit AS turn
                        CROSS JOIN LATERAL unnest(turn.retrieved_context_ids)
                            AS cited(chunk_id)
                        WHERE NOT EXISTS (
                            SELECT 1 FROM kb_chunk AS chunk
                            WHERE chunk.id = cited.chunk_id
                        )
                    ) THEN
                        RAISE EXCEPTION
                            'retrieved_context_ids value is not a kb_chunk.id';
                    END IF;
                END IF;

                IF to_regclass('public.turn_citation') IS NULL THEN
                    CREATE TABLE turn_citation (
                        turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                        chunk_id uuid NOT NULL REFERENCES kb_chunk (id),
                        ordinal integer NOT NULL,
                        PRIMARY KEY (turn_id, ordinal),
                        UNIQUE (turn_id, chunk_id)
                    );
                    CREATE TRIGGER turn_citation_append_only
                        BEFORE UPDATE OR DELETE ON turn_citation
                        FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'turn_audit'
                      AND column_name = 'retrieved_context_ids'
                ) THEN
                    INSERT INTO turn_citation (turn_id, chunk_id, ordinal)
                    SELECT turn.turn_id, cited.chunk_id, cited.ordinality - 1
                    FROM turn_audit AS turn
                    CROSS JOIN LATERAL unnest(turn.retrieved_context_ids)
                        WITH ORDINALITY AS cited(chunk_id, ordinality);
                    ALTER TABLE turn_audit DROP COLUMN retrieved_context_ids;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'turn_audit'
                      AND column_name = 'human_action'
                ) THEN
                    ALTER TABLE turn_audit DROP COLUMN human_action;
                END IF;

                -- The base migration seeds this row only when it runs.
                -- A catalogue stamped before human_action existed does not
                -- have it, and the DEC-0012 trigger rejects the CREATE.
                INSERT INTO protected_column_exemption (
                    schema_name, table_name, column_name, reason, decision_ref
                ) VALUES (
                    'public', 'human_action', 'action',
                    'Non-personal control data. Stays cleartext so '
                    'approve/edit/override/stop is a database constraint '
                    '(DEC-0012).',
                    'DEC-0012'
                )
                ON CONFLICT (schema_name, table_name, column_name) DO NOTHING;

                IF to_regclass('public.human_action') IS NULL THEN
                    CREATE TABLE human_action (
                        id uuid PRIMARY KEY,
                        turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                        tutor_id ciphertext NOT NULL,
                        action text NOT NULL,
                        edited_output ciphertext,
                        {acted_at},
                        CONSTRAINT human_action_kind CHECK (
                            action IN ('approve', 'edit', 'override', 'stop')
                        ),
                        CONSTRAINT human_action_edit_has_output CHECK (
                            action <> 'edit' OR edited_output IS NOT NULL
                        )
                    );
                    CREATE TRIGGER human_action_append_only
                        BEFORE UPDATE OR DELETE ON human_action
                        FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
                END IF;

                FOREACH required_column IN ARRAY ARRAY[
                    'model_revision',
                    'template_version',
                    'decoding_params',
                    'output_before_checks',
                    'output_after_checks',
                    'ai_disclosure',
                    'refused',
                    'safety_flags',
                    'source_support'
                ]
                LOOP
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'turn_audit'
                          AND column_name = required_column
                          AND is_nullable = 'NO'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE turn_audit ALTER COLUMN %I DROP NOT NULL',
                            required_column
                        );
                    END IF;
                END LOOP;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'turn_audit_generation_together'
                      AND conrelid = 'public.turn_audit'::regclass
                ) THEN
                    ALTER TABLE turn_audit
                        ADD CONSTRAINT turn_audit_generation_together
                        CHECK ({generation}
                        );
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'turn_audit_session_turn'
                      AND conrelid = 'public.turn_audit'::regclass
                ) THEN
                    ALTER TABLE turn_audit
                        ADD CONSTRAINT turn_audit_session_turn
                        UNIQUE (session_id, turn_index);
                END IF;
            END
            $upgrade$
            """,
            *self._privileges(role, "turn_citation"),
            *self._privileges(role, "human_action"),
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        role = self._role.identifier()
        digest = (
            "Digest, not plaintext. Encrypting it would make Article 12 "
            "verification depend on key availability (DEC-0012)."
        )
        clear = (
            "Not personal data. Required in cleartext for evidence "
            "and replay (DEC-0012)."
        )
        recorded_at = InstantColumn("recorded_at").required()
        return (
            f"""
            DO $downgrade$
            DECLARE
                gate_fk name;
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM turn_audit
                    WHERE model_revision IS NULL
                       OR template_version IS NULL
                       OR decoding_params IS NULL
                       OR output_before_checks IS NULL
                       OR output_after_checks IS NULL
                       OR ai_disclosure IS NULL
                       OR refused IS NULL
                       OR safety_flags IS NULL
                       OR source_support IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'absent generation columns block this downgrade';
                END IF;

                IF EXISTS (SELECT 1 FROM human_action) THEN
                    RAISE EXCEPTION
                        'human_action rows cannot return to a ciphertext column';
                END IF;

                INSERT INTO protected_column_exemption (
                    schema_name, table_name, column_name, reason, decision_ref
                ) VALUES
                    (
                        'public', 'turn_audit_restored', 'model_revision',
                        '{clear}', 'DEC-0012'
                    ),
                    (
                        'public', 'turn_audit_restored', 'policy_version',
                        '{clear}', 'DEC-0012'
                    ),
                    (
                        'public', 'turn_audit_restored', 'record_hash',
                        '{digest}', 'DEC-0012'
                    ),
                    (
                        'public', 'turn_audit_restored', 'previous_record_hash',
                        '{digest}', 'DEC-0012'
                    )
                ON CONFLICT (schema_name, table_name, column_name) DO NOTHING;

                CREATE TABLE turn_audit_restored (
                    turn_id uuid PRIMARY KEY,
                    session_id uuid NOT NULL REFERENCES tutoring_session (id),
                    turn_index integer NOT NULL,
                    learner_prompt_redacted ciphertext NOT NULL,
                    redacted_categories ciphertext NOT NULL,
                    retrieved_context_ids uuid[] NOT NULL,
                    model_revision text NOT NULL,
                    template_version ciphertext NOT NULL,
                    decoding_params ciphertext NOT NULL,
                    output_before_checks ciphertext NOT NULL,
                    output_after_checks ciphertext NOT NULL,
                    ai_disclosure ciphertext NOT NULL,
                    refused boolean NOT NULL,
                    safety_flags ciphertext NOT NULL,
                    source_support ciphertext NOT NULL,
                    human_action ciphertext,
                    policy_version text NOT NULL REFERENCES policy_version (version),
                    previous_record_hash text NOT NULL,
                    record_hash text NOT NULL,
                    {recorded_at}
                );

                INSERT INTO turn_audit_restored (
                    turn_id, session_id, turn_index,
                    learner_prompt_redacted, redacted_categories,
                    retrieved_context_ids,
                    model_revision, template_version, decoding_params,
                    output_before_checks, output_after_checks, ai_disclosure,
                    refused, safety_flags, source_support, human_action,
                    policy_version, previous_record_hash, record_hash, recorded_at
                )
                SELECT
                    turn.turn_id, turn.session_id, turn.turn_index,
                    turn.learner_prompt_redacted, turn.redacted_categories,
                    COALESCE(
                        (
                            SELECT array_agg(
                                citation.chunk_id ORDER BY citation.ordinal
                            )
                            FROM turn_citation AS citation
                            WHERE citation.turn_id = turn.turn_id
                        ),
                        ARRAY[]::uuid[]
                    ),
                    turn.model_revision, turn.template_version, turn.decoding_params,
                    turn.output_before_checks, turn.output_after_checks,
                    turn.ai_disclosure, turn.refused, turn.safety_flags,
                    turn.source_support, NULL,
                    turn.policy_version, turn.previous_record_hash,
                    turn.record_hash, turn.recorded_at
                FROM turn_audit AS turn;

                SELECT constraint_name.conname
                INTO gate_fk
                FROM pg_constraint AS constraint_name
                WHERE constraint_name.conrelid = 'public.gate_evaluation'::regclass
                  AND constraint_name.contype = 'f';

                IF gate_fk IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE gate_evaluation DROP CONSTRAINT %I',
                        gate_fk
                    );
                END IF;

                DROP TRIGGER IF EXISTS human_action_append_only ON human_action;
                DROP TRIGGER IF EXISTS turn_citation_append_only ON turn_citation;
                DROP TABLE human_action;
                DROP TABLE turn_citation;
                DROP TABLE turn_audit;
                ALTER TABLE turn_audit_restored RENAME TO turn_audit;

                DELETE FROM protected_column_exemption
                WHERE schema_name = 'public'
                  AND table_name = 'turn_audit_restored';

                CREATE TRIGGER turn_audit_append_only
                    BEFORE UPDATE OR DELETE ON turn_audit
                    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();

                ALTER TABLE gate_evaluation
                    ADD CONSTRAINT gate_evaluation_turn_id_fkey
                    FOREIGN KEY (turn_id) REFERENCES turn_audit (turn_id);

                REVOKE ALL ON TABLE turn_audit FROM PUBLIC, {role};
                GRANT INSERT, SELECT ON TABLE turn_audit TO {role};
                REVOKE UPDATE, DELETE, TRUNCATE ON TABLE turn_audit FROM {role};
            END
            $downgrade$
            """,
        )

    def _privileges(self, role: str, table: str) -> tuple[str, ...]:
        return (
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC, {role}",
            f"GRANT INSERT, SELECT ON TABLE {table} TO {role}",
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM {role}",
        )


class SupersededAuditSchema:
    """The audit catalogue revision ``46c99fd72506`` applied when it shipped.

    Kept so a test can stamp that revision over this shape and prove the
    upgrade still reaches the current catalogue. Fresh installs do not run it.
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        role = self._role.identifier()
        rolname = self._role.literal()
        recorded_at = InstantColumn("recorded_at").required()
        evaluated_at = InstantColumn("evaluated_at").required()
        return (
            f"""
            DO $role$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = {rolname}
                ) THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END
            $role$
            """,
            f"""
            CREATE TABLE turn_audit (
                turn_id uuid PRIMARY KEY,
                session_id uuid NOT NULL REFERENCES tutoring_session (id),
                turn_index integer NOT NULL,
                learner_prompt_redacted ciphertext NOT NULL,
                redacted_categories ciphertext NOT NULL,
                retrieved_context_ids uuid[] NOT NULL,
                model_revision text NOT NULL,
                template_version ciphertext NOT NULL,
                decoding_params ciphertext NOT NULL,
                output_before_checks ciphertext NOT NULL,
                output_after_checks ciphertext NOT NULL,
                ai_disclosure ciphertext NOT NULL,
                refused boolean NOT NULL,
                safety_flags ciphertext NOT NULL,
                source_support ciphertext NOT NULL,
                human_action ciphertext,
                policy_version text NOT NULL REFERENCES policy_version (version),
                previous_record_hash text NOT NULL,
                record_hash text NOT NULL,
                {recorded_at}
            )
            """,
            f"""
            CREATE TABLE gate_evaluation (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                gate_name text NOT NULL,
                decision text NOT NULL,
                reason ciphertext,
                policy_rule_id text NOT NULL,
                {evaluated_at},
                CONSTRAINT gate_evaluation_decision CHECK (
                    decision IN ('pass', 'pause', 'stop', 'not_evaluated')
                ),
                CONSTRAINT gate_evaluation_not_evaluated_reason CHECK (
                    decision <> 'not_evaluated' OR reason IS NOT NULL
                )
            )
            """,
            """
            CREATE FUNCTION reject_audit_mutation()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION
                    'append-only: % on % is forbidden', TG_OP, TG_TABLE_NAME;
            END;
            $$
            """,
            """
            CREATE TRIGGER turn_audit_append_only
                BEFORE UPDATE OR DELETE ON turn_audit
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            """
            CREATE TRIGGER gate_evaluation_append_only
                BEFORE UPDATE OR DELETE ON gate_evaluation
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            f"REVOKE ALL ON TABLE turn_audit FROM PUBLIC, {role}",
            f"REVOKE ALL ON TABLE gate_evaluation FROM PUBLIC, {role}",
            f"GRANT INSERT, SELECT ON TABLE turn_audit TO {role}",
            f"GRANT INSERT, SELECT ON TABLE gate_evaluation TO {role}",
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE turn_audit FROM {role}",
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE gate_evaluation FROM {role}",
        )


class RequestPathPrivileges:
    """SELECT on the tables a request reads. Writes stay with the owner.

    Retrieval joins ``kb_chunk`` to ``kb_document``. The policy reader
    selects ``policy_version``. Curation and publication are the operator
    path (DEC-0014), so this role is not granted INSERT on these tables.
    The audit migration already created the role and granted the audit
    tables; this grant is the read the request path was missing.
    """

    _TABLES = ("policy_version", "kb_document", "kb_chunk")

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Revoke everything, then grant SELECT on each request-path table."""
        role = self._role.identifier()
        granted: list[str] = []
        for table in self._TABLES:
            granted.append(f"REVOKE ALL ON TABLE {table} FROM PUBLIC, {role}")
            granted.append(f"GRANT SELECT ON TABLE {table} TO {role}")
        return tuple(granted)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the SELECT grant. The tables themselves stay."""
        role = self._role.identifier()
        return tuple(
            f"REVOKE SELECT ON TABLE {table} FROM {role}" for table in self._TABLES
        )


class LearnerHistoryColumnGrant:
    """SELECT on exactly the history columns a read needs (REQ-HISTORY).

    Column-level, not table-level: the application role can select
    ``learner_id``, ``retain_until`` and ``proficiency_level`` from
    ``learner``, and nothing else there. ``pseudonym`` stays unreadable to
    the request path even if an adapter were changed to select it. The
    Python allowlist narrows a read further; this grant is the floor the
    database enforces. ``learner_history_event.id`` is included so the
    read can order ties by the primary key; it is not a history field.

    ``REVOKE ALL ON TABLE`` does not remove column privileges, so the
    downgrade revokes the columns by name.
    """

    _COLUMNS = (
        ("learner", ("learner_id", "retain_until", "proficiency_level")),
        (
            "learner_history_event",
            ("learner_id", "item_id", "correct", "occurred_at", "id"),
        ),
    )

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Revoke table privileges, then grant SELECT on the named columns."""
        role = self._role.identifier()
        granted: list[str] = []
        for table, columns in self._COLUMNS:
            granted.append(f"REVOKE ALL ON TABLE {table} FROM PUBLIC, {role}")
            granted.append(
                f"GRANT SELECT ({', '.join(columns)}) ON TABLE {table} TO {role}"
            )
        return tuple(granted)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Revoke the column grants. The tables stay."""
        role = self._role.identifier()
        return tuple(
            f"REVOKE SELECT ({', '.join(columns)}) ON TABLE {table} FROM {role}"
            for table, columns in self._COLUMNS
        )


class LearnerHistoryEventIdGrant:
    """SELECT on ``learner_history_event.id`` for catalogues already migrated.

    The history grant class now includes ``id``. A database that applied
    that revision before ``id`` was added does not re-run it, so this
    grant repairs the privilege. Granting it again, on a fresh upgrade,
    changes nothing. The downgrade leaves ``id`` in place: the history
    grant owns that column, and its own downgrade revokes it.
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Grant SELECT on the event id. Idempotent if it is already held."""
        role = self._role.identifier()
        return (f"GRANT SELECT (id) ON TABLE learner_history_event TO {role}",)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Leave the id grant. The history grant's downgrade revokes it."""
        return ()


class TutoringSessionColumnGrant:
    """SELECT on the session columns a turn must check before it reads.

    Column-level: ``id``, ``learner_id`` and ``stopped_at`` only. The
    request path confirms the session is this learner's and still open
    (REQ-MINOR). ``tutor_id`` and ``stop_reason`` stay unreadable, so a
    check cannot become a way to read the tutor's identity or the reason
    the session was stopped.
    """

    _COLUMNS = ("id", "learner_id", "stopped_at")

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Revoke table privileges, then grant SELECT on the named columns."""
        role = self._role.identifier()
        columns = ", ".join(self._COLUMNS)
        return (
            f"REVOKE ALL ON TABLE tutoring_session FROM PUBLIC, {role}",
            f"GRANT SELECT ({columns}) ON TABLE tutoring_session TO {role}",
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Revoke the column grant. The table stays."""
        role = self._role.identifier()
        columns = ", ".join(self._COLUMNS)
        return (f"REVOKE SELECT ({columns}) ON TABLE tutoring_session FROM {role}",)


class TurnAuditOpenSession:
    """Refuse a ``turn_audit`` insert into a stopped session (ARCHITECTURE §8).

    The request path checks the session before retrieval, but the model can
    run for minutes after that. A stop committed in between would otherwise
    see its session take one more turn. This trigger checks again at the
    insert, in the database, so no request path can skip it.

    ``FOR SHARE`` locks the session row until the turn commits. A stop that
    is still uncommitted makes the insert wait and then see it; a stop that
    arrives after the insert waits for the turn. Either way the turn and the
    stop are ordered, and a stopped session never gains a row.

    ``SECURITY DEFINER``: ``FOR SHARE`` needs UPDATE privilege, which the
    application role must not hold on ``tutoring_session``. The function
    runs as the migration owner with a fixed ``search_path``, reads
    ``stopped_at`` only, and cannot be called except as this trigger.
    """

    SQLSTATE = "TS001"

    def statements(self) -> tuple[str, ...]:
        """Create the function and the trigger. The role gains no privilege."""
        return (
            f"""
            CREATE FUNCTION reject_turn_in_stopped_session()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                stopped timestamptz;
            BEGIN
                SELECT stopped_at INTO stopped
                FROM public.tutoring_session
                WHERE id = NEW.session_id
                FOR SHARE;
                IF stopped IS NOT NULL THEN
                    RAISE EXCEPTION 'session is stopped'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                RETURN NEW;
            END;
            $$
            """,
            "REVOKE ALL ON FUNCTION reject_turn_in_stopped_session() FROM PUBLIC",
            """
            CREATE TRIGGER turn_audit_open_session
                BEFORE INSERT ON turn_audit
                FOR EACH ROW EXECUTE FUNCTION reject_turn_in_stopped_session()
            """,
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the trigger, then its function."""
        return (
            "DROP TRIGGER IF EXISTS turn_audit_open_session ON turn_audit",
            "DROP FUNCTION IF EXISTS reject_turn_in_stopped_session()",
        )


class HistoryOutcomeEncryption:
    """Convert ``learner_history_event.correct`` from boolean to ciphertext.

    In place, without losing an outcome: a sealed column is added, each row's
    outcome is sealed by the application (DEC-0012 — the database never holds
    the key), and the boolean column is dropped only after every row has its
    sealed value. The outcome is sealed as one byte, so the two outcomes
    cannot be told apart by ciphertext length (``HistoryOutcomeCodec``).

    ``cipher`` is called only when there are rows to convert, so a fresh
    database upgrades without a key. The downgrade reverses it the same way.
    """

    def upgrade(
        self,
        connection: psycopg.Connection,
        cipher: Callable[[], CipherPort],
        outcomes: HistoryOutcomeCodec,
    ) -> None:
        """Seal every boolean outcome, then replace the column."""
        connection.execute(
            "ALTER TABLE learner_history_event ADD COLUMN correct_sealed ciphertext"
        )
        rows = connection.execute(
            "SELECT id, correct FROM learner_history_event"
        ).fetchall()
        if rows:
            sealer = cipher()
            for row_id, correct in rows:
                connection.execute(
                    "UPDATE learner_history_event "
                    "SET correct_sealed = %s WHERE id = %s",
                    (sealer.encrypt(outcomes.encode(bool(correct))), row_id),
                )
        connection.execute(
            "ALTER TABLE learner_history_event ALTER COLUMN correct_sealed SET NOT NULL"
        )
        connection.execute("ALTER TABLE learner_history_event DROP COLUMN correct")
        connection.execute(
            "ALTER TABLE learner_history_event RENAME COLUMN correct_sealed TO correct"
        )

    def downgrade(
        self,
        connection: psycopg.Connection,
        cipher: Callable[[], CipherPort],
        outcomes: HistoryOutcomeCodec,
    ) -> None:
        """Open every sealed outcome, then restore the boolean column."""
        connection.execute(
            "ALTER TABLE learner_history_event ADD COLUMN correct_plain boolean"
        )
        rows = connection.execute(
            "SELECT id, correct FROM learner_history_event"
        ).fetchall()
        if rows:
            opener = cipher()
            for row_id, sealed in rows:
                connection.execute(
                    "UPDATE learner_history_event SET correct_plain = %s WHERE id = %s",
                    (outcomes.decode(opener.decrypt(bytes(sealed))), row_id),
                )
        connection.execute(
            "ALTER TABLE learner_history_event ALTER COLUMN correct_plain SET NOT NULL"
        )
        connection.execute("ALTER TABLE learner_history_event DROP COLUMN correct")
        connection.execute(
            "ALTER TABLE learner_history_event RENAME COLUMN correct_plain TO correct"
        )


class MarkSessionStopped:
    """Let the application stop a session without an UPDATE grant.

    ``FOR UPDATE`` on ``tutoring_session`` needs a privilege the request
    role must not hold (the same reason ``TurnAuditOpenSession`` is a
    security definer). The function sets ``stopped_at`` and the sealed
    ``stop_reason``, and raises ``SS001`` when the session is missing or
    already stopped. The turns already written stay (REQ-DASH).
    """

    SQLSTATE = "SS001"

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Create the function and grant execute to the application role."""
        role = self._role.identifier()
        return (
            f"""
            CREATE FUNCTION mark_session_stopped(
                target uuid,
                stopped timestamptz,
                reason bytea
            )
            RETURNS void
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                existing timestamptz;
            BEGIN
                SELECT stopped_at INTO existing
                FROM public.tutoring_session
                WHERE id = target
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'session is not known'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                IF existing IS NOT NULL THEN
                    RAISE EXCEPTION 'session is stopped'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                UPDATE public.tutoring_session
                SET stopped_at = stopped,
                    stop_reason = reason
                WHERE id = target;
            END;
            $$
            """,
            "REVOKE ALL ON FUNCTION mark_session_stopped(uuid, timestamptz, bytea) "
            "FROM PUBLIC",
            f"GRANT EXECUTE ON FUNCTION mark_session_stopped(uuid, timestamptz, bytea) "
            f"TO {role}",
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the function. Sessions already stopped stay stopped."""
        return (
            "DROP FUNCTION IF EXISTS mark_session_stopped(uuid, timestamptz, bytea)",
        )


class RetentionPurgeLog:
    """An append-only note that a learner's personal rows were purged.

    ``learner_id`` is the pseudonymous key. ``purged_at`` is an instant.
    ``history_rows`` is a count. None of those is learner text, so the
    table has no ciphertext column and no plaintext exemption to register
    (DEC-0012). The purge itself is the owner's job; this role may only
    read the log (REQ-MINOR).
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Create the log, refuse updates, and grant select."""
        role = self._role.identifier()
        return (
            """
            CREATE TABLE retention_purge (
                id uuid PRIMARY KEY,
                learner_id uuid NOT NULL,
                purged_at timestamptz NOT NULL,
                history_rows integer NOT NULL
            )
            """,
            """
            CREATE TRIGGER retention_purge_append_only
                BEFORE UPDATE OR DELETE ON retention_purge
                FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
            """,
            f"REVOKE ALL ON TABLE retention_purge FROM PUBLIC, {role}",
            f"GRANT SELECT ON TABLE retention_purge TO {role}",
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the log. A downgrade does not restore purged rows."""
        return (
            "DROP TRIGGER IF EXISTS retention_purge_append_only ON retention_purge",
            "DROP TABLE IF EXISTS retention_purge",
        )


class OpenSessionFunction:
    """Let the application role open a session without INSERT on the table.

    The same shape as ``MarkSessionStopped``: a security-definer function
    owns the write, so the role's grant on ``tutoring_session`` stays a
    column-level SELECT. The function refuses, with ``OS001``, a learner
    that is not known or whose ``retain_until`` has passed — a purged
    learner cannot be given a new session (REQ-MINOR). ``tutor`` arrives
    sealed; the database never sees the key (DEC-0012).
    """

    SQLSTATE = "OS001"

    _SIGNATURE = "open_session(uuid, uuid, bytea, timestamptz)"

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Create the function and grant execute to the application role."""
        role = self._role.identifier()
        return (
            f"""
            CREATE FUNCTION open_session(
                target_session uuid,
                target_learner uuid,
                tutor bytea,
                started timestamptz
            )
            RETURNS void
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                retained timestamptz;
            BEGIN
                SELECT retain_until INTO retained
                FROM public.learner
                WHERE learner_id = target_learner;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'learner is not known'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                IF retained <= started THEN
                    RAISE EXCEPTION 'learner retention has ended'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                INSERT INTO public.tutoring_session (
                    id, tutor_id, learner_id, started_at
                ) VALUES (
                    target_session, tutor, target_learner, started
                );
            END;
            $$
            """,
            f"REVOKE ALL ON FUNCTION {self._SIGNATURE} FROM PUBLIC",
            f"GRANT EXECUTE ON FUNCTION {self._SIGNATURE} TO {role}",
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the function. Sessions it opened stay."""
        return (f"DROP FUNCTION IF EXISTS {self._SIGNATURE}",)


class SessionStartedAtGrant:
    """SELECT on ``tutoring_session.started_at``, so the dashboard can order.

    An instant, not personal data; ``tutor_id`` and ``stop_reason`` stay
    unreadable. Without it the list could only be ordered by a random UUID.
    """

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Grant the one column."""
        role = self._role.identifier()
        return (f"GRANT SELECT (started_at) ON TABLE tutoring_session TO {role}",)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Revoke the one column."""
        role = self._role.identifier()
        return (f"REVOKE SELECT (started_at) ON TABLE tutoring_session FROM {role}",)


class HumanActionChain:
    """Tutor actions get their own hash chain and database-enforced rules.

    Before this, ``human_action`` was the one audit table outside a chain:
    a row inserted later, or back-dated, left ``/audit`` reporting intact.
    Each new row now carries ``session_id``, ``action_index``,
    ``previous_action_hash`` and ``action_hash`` — the same construction as
    ``turn_audit`` (REQ-AUDIT). Rows written before this revision keep the
    four columns null and are reported as unchained, not rewritten: the
    table is append-only.

    The insert trigger refuses, with ``HA001``:

    - a turn that is not known, or not in the row's session;
    - a session that is stopped (the review found approve and edit were
      accepted after a stop);
    - approve or edit on a turn the model never ran on — there is no draft
      to release.

    ``human_action_one_decision`` allows one approve, edit or override per
    turn; a stop may still follow it. ``FOR SHARE`` on the session row
    orders the action against a concurrent stop, as ``TurnAuditOpenSession``
    does for turns.
    """

    SQLSTATE = "HA001"

    _DIGEST = (
        "Digest, not plaintext. Encrypting it would make Article 12 "
        "verification depend on key availability (DEC-0012)."
    )

    def statements(self) -> tuple[str, ...]:
        """Register the digest exemptions, then add the columns and guards."""
        return (
            f"""
            INSERT INTO protected_column_exemption (
                schema_name, table_name, column_name, reason, decision_ref
            ) VALUES
                ('public', 'human_action', 'previous_action_hash',
                 '{self._DIGEST}', 'DEC-0012'),
                ('public', 'human_action', 'action_hash',
                 '{self._DIGEST}', 'DEC-0012')
            ON CONFLICT (schema_name, table_name, column_name) DO NOTHING
            """,
            """
            ALTER TABLE human_action
                ADD COLUMN session_id uuid REFERENCES tutoring_session (id),
                ADD COLUMN action_index integer,
                ADD COLUMN previous_action_hash text,
                ADD COLUMN action_hash text
            """,
            """
            ALTER TABLE human_action
                ADD CONSTRAINT human_action_chained CHECK (
                    session_id IS NOT NULL
                    AND action_index IS NOT NULL
                    AND action_index >= 0
                    AND previous_action_hash IS NOT NULL
                    AND action_hash IS NOT NULL
                ) NOT VALID
            """,
            """
            ALTER TABLE human_action
                ADD CONSTRAINT human_action_session_index
                UNIQUE (session_id, action_index)
            """,
            """
            CREATE UNIQUE INDEX human_action_one_decision
                ON human_action (turn_id)
                WHERE action IN ('approve', 'edit', 'override')
                  AND session_id IS NOT NULL
            """,
            f"""
            CREATE FUNCTION guard_human_action()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                turn_session uuid;
                generated boolean;
                stopped timestamptz;
            BEGIN
                SELECT session_id, output_after_checks IS NOT NULL
                INTO turn_session, generated
                FROM public.turn_audit
                WHERE turn_id = NEW.turn_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'turn is not known'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                IF NEW.session_id IS DISTINCT FROM turn_session THEN
                    RAISE EXCEPTION 'turn is not in this session'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                SELECT stopped_at INTO stopped
                FROM public.tutoring_session
                WHERE id = turn_session
                FOR SHARE;
                IF stopped IS NOT NULL THEN
                    RAISE EXCEPTION 'session is stopped'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                IF NEW.action IN ('approve', 'edit') AND NOT generated THEN
                    RAISE EXCEPTION 'the model did not run on this turn'
                        USING ERRCODE = '{self.SQLSTATE}';
                END IF;
                RETURN NEW;
            END;
            $$
            """,
            "REVOKE ALL ON FUNCTION guard_human_action() FROM PUBLIC",
            """
            CREATE TRIGGER human_action_guard
                BEFORE INSERT ON human_action
                FOR EACH ROW EXECUTE FUNCTION guard_human_action()
            """,
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the guards and the chain columns, then the exemptions."""
        return (
            "DROP TRIGGER IF EXISTS human_action_guard ON human_action",
            "DROP FUNCTION IF EXISTS guard_human_action()",
            "DROP INDEX IF EXISTS human_action_one_decision",
            """
            ALTER TABLE human_action
                DROP CONSTRAINT IF EXISTS human_action_session_index,
                DROP CONSTRAINT IF EXISTS human_action_chained,
                DROP COLUMN IF EXISTS action_hash,
                DROP COLUMN IF EXISTS previous_action_hash,
                DROP COLUMN IF EXISTS action_index,
                DROP COLUMN IF EXISTS session_id
            """,
            """
            DELETE FROM protected_column_exemption
            WHERE schema_name = 'public'
              AND table_name = 'human_action'
              AND column_name IN ('previous_action_hash', 'action_hash')
            """,
        )


class StopRequiresAction:
    """``mark_session_stopped`` refuses unless the stop was logged first.

    The function is granted to the application role, so before this any
    code on that role could stop a session with no ``human_action`` row
    and "every tutor action produces an audit entry" rested on adapter
    discipline (REQ-DASH). The replacement requires a ``stop`` row for the
    session at the same instant, written earlier in the same transaction.
    """

    _SIGNATURE = "mark_session_stopped(uuid, timestamptz, bytea)"

    def __init__(self, role: ApplicationRole) -> None:
        self._role = role

    def statements(self) -> tuple[str, ...]:
        """Replace the function body. The grant is kept."""
        sqlstate = MarkSessionStopped.SQLSTATE
        return (
            f"""
            CREATE OR REPLACE FUNCTION mark_session_stopped(
                target uuid,
                stopped timestamptz,
                reason bytea
            )
            RETURNS void
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                existing timestamptz;
            BEGIN
                SELECT stopped_at INTO existing
                FROM public.tutoring_session
                WHERE id = target
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'session is not known'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                IF existing IS NOT NULL THEN
                    RAISE EXCEPTION 'session is stopped'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM public.human_action
                    WHERE session_id = target
                      AND action = 'stop'
                      AND acted_at = stopped
                ) THEN
                    RAISE EXCEPTION 'a stop is logged as a tutor action first'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                UPDATE public.tutoring_session
                SET stopped_at = stopped,
                    stop_reason = reason
                WHERE id = target;
            END;
            $$
            """,
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Restore the body that did not require the logged stop."""
        original = MarkSessionStopped(self._role).statements()[0]
        return (original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),)


class TurnAuditHistorySnapshot:
    """The history a turn was generated with, sealed on its audit row.

    Replay re-runs generation from the record. The prompt and the cited
    chunks were already recorded; the allowlisted history snapshot was not,
    so a replay could not render the same prompt. The column is ciphertext
    (DEC-0012) and null when retrieval never ran.
    """

    def statements(self) -> tuple[str, ...]:
        """Add the sealed column."""
        return ("ALTER TABLE turn_audit ADD COLUMN history_snapshot ciphertext",)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Drop the column."""
        return ("ALTER TABLE turn_audit DROP COLUMN IF EXISTS history_snapshot",)


class TurnAuditOutcomeCheck:
    """Model columns need an outcome; an outcome alone is a refusal.

    The replaced check made every generation column null together or
    present together, so a refusal before the model stored nothing: not the
    refusal, not the disclosure, not the flags that caused it (REQ-AUDIT).
    The model group is what the model produced; the outcome group is what
    generation decided. It mirrors ``TurnAuditRecord.generation_fields_agree``.
    """

    NAME = "turn_audit_generation_outcome"

    def expression(self) -> str:
        """Both groups agree internally; an outcome without the model refused."""
        return """
                        (
                            (
                                model_revision IS NULL
                                AND template_version IS NULL
                                AND decoding_params IS NULL
                                AND output_before_checks IS NULL
                                AND source_support IS NULL
                            )
                            OR (
                                model_revision IS NOT NULL
                                AND template_version IS NOT NULL
                                AND decoding_params IS NOT NULL
                                AND output_before_checks IS NOT NULL
                                AND source_support IS NOT NULL
                            )
                        )
                        AND (
                            (
                                output_after_checks IS NULL
                                AND ai_disclosure IS NULL
                                AND refused IS NULL
                                AND safety_flags IS NULL
                            )
                            OR (
                                output_after_checks IS NOT NULL
                                AND ai_disclosure IS NOT NULL
                                AND refused IS NOT NULL
                                AND safety_flags IS NOT NULL
                            )
                        )
                        AND (model_revision IS NULL OR refused IS NOT NULL)
                        AND (
                            model_revision IS NOT NULL
                            OR refused IS NULL
                            OR refused
                        )"""


class TurnAuditEvidence:
    """Prompt flags and the cited-text digest, and the refusal's outcome.

    ``prompt_safety_flags`` is what the classifier raised on the redacted
    prompt, sealed (DEC-0012). ``context_digest`` binds the record to the
    cited chunk text; it is a digest, registered as a cleartext exemption
    for the reason ``record_hash`` is. Both are null on rows sealed before
    this revision, and the record hash omits them there.
    """

    _DIGEST = (
        "Digest of the cited chunk text, not the text. Encrypting it would "
        "make replay verification depend on key availability (DEC-0012)."
    )

    def statements(self) -> tuple[str, ...]:
        """Register the exemption, add the columns, then swap the check."""
        outcome = TurnAuditOutcomeCheck()
        return (
            f"""
            INSERT INTO protected_column_exemption (
                schema_name, table_name, column_name, reason, decision_ref
            ) VALUES (
                'public', 'turn_audit', 'context_digest',
                '{self._DIGEST}', 'DEC-0012'
            )
            ON CONFLICT (schema_name, table_name, column_name) DO NOTHING
            """,
            """
            ALTER TABLE turn_audit
                ADD COLUMN prompt_safety_flags ciphertext,
                ADD COLUMN context_digest text
                    CONSTRAINT turn_audit_context_digest_shape
                    CHECK (context_digest ~ '^[0-9a-f]{64}$')
            """,
            "ALTER TABLE turn_audit DROP CONSTRAINT turn_audit_generation_together",
            f"""
            ALTER TABLE turn_audit
                ADD CONSTRAINT {outcome.NAME} CHECK ({outcome.expression()}
                )
            """,
        )

    def downgrade_statements(self) -> tuple[str, ...]:
        """Restore the all-or-none check. A stored refusal refuses the downgrade."""
        generation = TurnAuditGenerationCheck().expression()
        return (
            f"ALTER TABLE turn_audit DROP CONSTRAINT {TurnAuditOutcomeCheck.NAME}",
            f"""
            ALTER TABLE turn_audit
                ADD CONSTRAINT turn_audit_generation_together CHECK ({generation}
                )
            """,
            """
            ALTER TABLE turn_audit
                DROP COLUMN context_digest,
                DROP COLUMN prompt_safety_flags
            """,
            """
            DELETE FROM protected_column_exemption
            WHERE schema_name = 'public'
              AND table_name = 'turn_audit'
              AND column_name = 'context_digest'
            """,
        )


class ReleaseRequiresPassedGates:
    """``guard_human_action`` also refuses approving a held or refused draft.

    The function ``HumanActionChain`` installed let approve through for any
    turn the model ran on, so a gate's ``pause`` or ``stop`` did not change
    what the tutor could release (REQ-GATES). Approve now needs four
    ``pass`` rows and a draft the agent did not refuse. Edit still needs a
    model draft; that test reads ``output_before_checks``, because a
    refusal before the model now stores an outcome with no draft.
    """

    def statements(self) -> tuple[str, ...]:
        """Replace the function body. The trigger and its grants are kept."""
        return (self._function(release_rule=True),)

    def downgrade_statements(self) -> tuple[str, ...]:
        """Restore the body ``HumanActionChain`` installed."""
        return (self._function(release_rule=False),)

    def _function(self, *, release_rule: bool) -> str:
        sqlstate = HumanActionChain.SQLSTATE
        generated = (
            "output_before_checks IS NOT NULL"
            if release_rule
            else "output_after_checks IS NOT NULL"
        )
        approve = (
            f"""
                IF NEW.action = 'approve' AND refused_draft THEN
                    RAISE EXCEPTION 'the agent refused this draft'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                IF NEW.action = 'approve' AND (
                    SELECT count(*) FROM public.gate_evaluation
                    WHERE turn_id = NEW.turn_id AND decision = 'pass'
                ) <> 4 THEN
                    RAISE EXCEPTION 'this draft did not pass every gate'
                        USING ERRCODE = '{sqlstate}';
                END IF;"""
            if release_rule
            else ""
        )
        return f"""
            CREATE OR REPLACE FUNCTION guard_human_action()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                turn_session uuid;
                generated boolean;
                refused_draft boolean;
                stopped timestamptz;
            BEGIN
                SELECT session_id, {generated}, coalesce(refused, false)
                INTO turn_session, generated, refused_draft
                FROM public.turn_audit
                WHERE turn_id = NEW.turn_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'turn is not known'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                IF NEW.session_id IS DISTINCT FROM turn_session THEN
                    RAISE EXCEPTION 'turn is not in this session'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                SELECT stopped_at INTO stopped
                FROM public.tutoring_session
                WHERE id = turn_session
                FOR SHARE;
                IF stopped IS NOT NULL THEN
                    RAISE EXCEPTION 'session is stopped'
                        USING ERRCODE = '{sqlstate}';
                END IF;
                IF NEW.action IN ('approve', 'edit') AND NOT generated THEN
                    RAISE EXCEPTION 'the model did not run on this turn'
                        USING ERRCODE = '{sqlstate}';
                END IF;{approve}
                RETURN NEW;
            END;
            $$
            """
