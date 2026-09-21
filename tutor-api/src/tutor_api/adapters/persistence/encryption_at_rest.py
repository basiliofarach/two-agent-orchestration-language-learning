"""Schema guard: plaintext on a protected table is a migration error (DEC-0012)."""

import psycopg
from pydantic import BaseModel, ConfigDict, Field


class ColumnExemption(BaseModel):
    """One plaintext column, with the reason DEC-0012 requires to be enumerable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_name: str = Field(min_length=1)
    column_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decision_ref: str = "DEC-0012"


class EncryptionAtRestSchema:
    """Install the ciphertext domain, the exemption registry, and the trigger.

    Protected tables are the learner, session, and audit tables. Knowledge-base
    tables stay outside that list: DEC-0012 records them as curated material,
    not personal data, and their exemption rows are still seeded so the set is
    a query. ``pgcrypto`` is not used; the application encrypts.
    """

    def protected_tables(self) -> tuple[str, ...]:
        return (
            "turn_audit",
            "gate_evaluation",
            "learner",
            "learner_history",
            "learner_history_event",
            "tutoring_session",
        )

    def exemptions(self) -> tuple[ColumnExemption, ...]:
        digest = (
            "Digest, not plaintext. Encrypting it would make Article 12 "
            "verification depend on key availability (DEC-0012)."
        )
        pseudonym = (
            "Pseudonymous UUID and a join key. Deterministic encryption "
            "would leak equality (DEC-0012)."
        )
        not_personal = (
            "Not personal data. Required in cleartext for evidence "
            "and replay (DEC-0012)."
        )
        curated = (
            "Not personal data. Public curated material with provenance (DEC-0012)."
        )
        return (
            ColumnExemption(
                table_name="kb_chunk",
                column_name="embedding",
                reason=(
                    "ANN search over ciphertext is not possible. The indexed "
                    "corpus is the vetted knowledge base, not learner text (DEC-0012)."
                ),
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="record_hash",
                reason=digest,
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="previous_record_hash",
                reason=digest,
            ),
            ColumnExemption(
                table_name="learner",
                column_name="learner_id",
                reason=pseudonym,
            ),
            ColumnExemption(
                table_name="learner_history",
                column_name="learner_id",
                reason=pseudonym,
            ),
            ColumnExemption(
                table_name="learner_history_event",
                column_name="learner_id",
                reason=pseudonym,
            ),
            ColumnExemption(
                table_name="kb_document",
                column_name="source_uri",
                reason=curated,
            ),
            ColumnExemption(
                table_name="kb_document",
                column_name="version",
                reason=curated,
            ),
            ColumnExemption(
                table_name="kb_document",
                column_name="review_status",
                reason=curated,
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="policy_version",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="model_revision",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="recorded_at",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="turn_audit",
                column_name="turn_id",
                reason=not_personal,
            ),
        )

    def statements(self) -> tuple[str, ...]:
        names = ", ".join(f"'{table}'" for table in self.protected_tables())
        function = f"""
CREATE OR REPLACE FUNCTION dec0012_reject_plaintext_columns()
RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    offending text;
BEGIN
    SELECT string_agg(
               format('%I.%I (%s)', c.relname, a.attname, t.typname),
               ', '
           )
      INTO offending
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_type t ON t.oid = a.atttypid
      LEFT JOIN protected_column_exemption e
             ON e.table_name = c.relname AND e.column_name = a.attname
     WHERE n.nspname = 'public'
       AND c.relkind = 'r'
       AND c.relname IN ({names})
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND t.typname IN ('text', 'varchar', 'bpchar', 'json', 'jsonb', 'bytea')
       AND e.column_name IS NULL;

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
            'DEC-0012: plaintext column on a protected table: %', offending
            USING HINT = 'Use the ciphertext domain, or register an exemption '
                         'in protected_column_exemption with a reason.';
    END IF;
END;
$$
"""
        return (
            """
CREATE DOMAIN ciphertext AS bytea
    CONSTRAINT dec0012_envelope_shape CHECK (
        octet_length(VALUE) >= 45
        AND get_byte(VALUE, 0) = 1
    )
""",
            """
CREATE TABLE protected_column_exemption (
    table_name text NOT NULL,
    column_name text NOT NULL,
    reason text NOT NULL CHECK (length(trim(reason)) > 0),
    decision_ref text NOT NULL,
    PRIMARY KEY (table_name, column_name)
)
""",
            function,
            """
CREATE EVENT TRIGGER dec0012_no_plaintext_columns
    ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE', 'ALTER TABLE')
    EXECUTE FUNCTION dec0012_reject_plaintext_columns()
""",
        )

    def install(self, connection: psycopg.Connection) -> None:
        """Apply the guard and commit it."""
        with connection.cursor() as cursor:
            for statement in self.statements():
                cursor.execute(statement)
            for exemption in self.exemptions():
                cursor.execute(
                    """
                    INSERT INTO protected_column_exemption (
                        table_name, column_name, reason, decision_ref
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        exemption.table_name,
                        exemption.column_name,
                        exemption.reason,
                        exemption.decision_ref,
                    ),
                )
        connection.commit()
