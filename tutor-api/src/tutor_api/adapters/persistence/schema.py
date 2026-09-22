"""Non-audit tables (BE-05) and the append-only audit tables (BE-06)."""

import re


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


class BaseSchema:
    """Knowledge base, learner, session, and policy tables."""

    def embedding_dimensions(self) -> int:
        return 768

    def statements(self) -> tuple[str, ...]:
        width = self.embedding_dimensions()
        return (
            "CREATE EXTENSION IF NOT EXISTS vector",
            """
            CREATE TABLE policy_version (
                version text PRIMARY KEY,
                allowed_actions ciphertext NOT NULL,
                denied_actions ciphertext NOT NULL,
                escalation_rules ciphertext NOT NULL,
                article_mappings ciphertext NOT NULL,
                effective_from timestamptz NOT NULL
            )
            """,
            """
            CREATE TABLE kb_document (
                id uuid PRIMARY KEY,
                source_uri text NOT NULL,
                version text NOT NULL,
                review_status text NOT NULL,
                reviewed_by ciphertext,
                reviewed_at timestamptz,
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
            """
            CREATE TABLE learner (
                learner_id uuid PRIMARY KEY,
                pseudonym ciphertext NOT NULL,
                proficiency_level ciphertext NOT NULL,
                retain_until timestamptz NOT NULL
            )
            """,
            """
            CREATE TABLE learner_history_event (
                id uuid PRIMARY KEY,
                learner_id uuid NOT NULL REFERENCES learner (learner_id),
                item_id ciphertext NOT NULL,
                correct boolean NOT NULL,
                occurred_at timestamptz NOT NULL
            )
            """,
            """
            CREATE TABLE tutoring_session (
                id uuid PRIMARY KEY,
                tutor_id ciphertext NOT NULL,
                learner_id uuid NOT NULL REFERENCES learner (learner_id),
                started_at timestamptz NOT NULL,
                stopped_at timestamptz,
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
                recorded_at timestamptz NOT NULL,
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
            """
            CREATE TABLE gate_evaluation (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                gate_name text NOT NULL,
                decision text NOT NULL,
                reason ciphertext,
                policy_rule_id text NOT NULL,
                evaluated_at timestamptz NOT NULL,
                CONSTRAINT gate_evaluation_decision CHECK (
                    decision IN ('pass', 'pause', 'stop', 'not_evaluated')
                ),
                CONSTRAINT gate_evaluation_not_evaluated_reason CHECK (
                    decision <> 'not_evaluated' OR reason IS NOT NULL
                )
            )
            """,
            """
            CREATE TABLE human_action (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                tutor_id ciphertext NOT NULL,
                action text NOT NULL,
                edited_output ciphertext,
                acted_at timestamptz NOT NULL,
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
                        acted_at timestamptz NOT NULL,
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
                    recorded_at timestamptz NOT NULL
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
            """
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
                recorded_at timestamptz NOT NULL
            )
            """,
            """
            CREATE TABLE gate_evaluation (
                id uuid PRIMARY KEY,
                turn_id uuid NOT NULL REFERENCES turn_audit (turn_id),
                gate_name text NOT NULL,
                decision text NOT NULL,
                reason ciphertext,
                policy_rule_id text NOT NULL,
                evaluated_at timestamptz NOT NULL,
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
