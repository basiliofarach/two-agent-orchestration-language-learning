"""Non-audit tables (BE-05) and the append-only audit tables (BE-06)."""

import re


class ApplicationRole:
    """The role granted insert and select on the audit tables.

    Injected, not fixed. ``docker/postgres/init/01-roles.sh`` creates the login
    from ``POSTGRES_APP_USER``; with the name hard-coded, a deployment that
    overrode that variable had the audit privileges granted to a NOLOGIN
    placeholder this migration created, while the login the application
    actually uses received none — a silent loss of the REQ-AUDIT control.
    :class:`~tutor_api.settings.DatabaseSettings` resolves the name from the
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


class AuditSchema:
    """Append-only ``turn_audit`` and ``gate_evaluation`` (BE-06, DEC-0006)."""

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

    def downgrade_statements(self) -> tuple[str, ...]:
        return (
            "DROP TRIGGER IF EXISTS gate_evaluation_append_only ON gate_evaluation",
            "DROP TRIGGER IF EXISTS turn_audit_append_only ON turn_audit",
            "DROP FUNCTION IF EXISTS reject_audit_mutation()",
            "DROP TABLE IF EXISTS gate_evaluation",
            "DROP TABLE IF EXISTS turn_audit",
        )
