"""Schema guard: plaintext on a stored table is a migration error (DEC-0012)."""

import psycopg
from pydantic import BaseModel, ConfigDict, Field


class ColumnExemption(BaseModel):
    """One plaintext column, with the reason DEC-0012 requires to be enumerable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_name: str = Field(default="public", min_length=1)
    table_name: str = Field(min_length=1)
    column_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decision_ref: str = "DEC-0012"


class EncryptionAtRestSchema:
    """Install the ciphertext domain, the exemption registry, and the trigger.

    The trigger watches every ordinary table in every application schema, not
    only ``public``: a migration that creates a schema of its own must not be
    able to store cleartext there. A migration fails unless each
    cleartext-shaped column is the ``ciphertext`` domain or an exemption
    registered against that schema. ``pgcrypto`` is not used.
    """

    def _plaintext_type_names(self) -> tuple[str, ...]:
        return (
            "text",
            "varchar",
            "bpchar",
            "json",
            "jsonb",
            "bytea",
            "_text",
            "_varchar",
            "_bpchar",
            "_json",
            "_jsonb",
            "_bytea",
        )

    def _exemptions(self) -> tuple[ColumnExemption, ...]:
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
        registry = (
            "Exemption registry. The reason must stay readable in SQL "
            "so the evidence query can be answered (DEC-0012)."
        )
        revision = (
            "Alembic revision id. Not personal data. Required in "
            "cleartext for the migration runner (DEC-0012)."
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
            ColumnExemption(
                table_name="protected_column_exemption",
                column_name="schema_name",
                reason=registry,
            ),
            ColumnExemption(
                table_name="protected_column_exemption",
                column_name="table_name",
                reason=registry,
            ),
            ColumnExemption(
                table_name="protected_column_exemption",
                column_name="column_name",
                reason=registry,
            ),
            ColumnExemption(
                table_name="protected_column_exemption",
                column_name="reason",
                reason=registry,
            ),
            ColumnExemption(
                table_name="protected_column_exemption",
                column_name="decision_ref",
                reason=registry,
            ),
            ColumnExemption(
                table_name="alembic_version",
                column_name="version_num",
                reason=revision,
            ),
            ColumnExemption(
                table_name="policy_version",
                column_name="version",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="gate_evaluation",
                column_name="gate_name",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="gate_evaluation",
                column_name="decision",
                reason=not_personal,
            ),
            ColumnExemption(
                table_name="gate_evaluation",
                column_name="policy_rule_id",
                reason=not_personal,
            ),
        )

    def _statements(self) -> tuple[str, ...]:
        type_names = ", ".join(f"'{name}'" for name in self._plaintext_type_names())
        function = f"""
CREATE OR REPLACE FUNCTION dec0012_reject_plaintext_columns()
RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    offending text;
BEGIN
    SELECT string_agg(
               format('%I.%I.%I (%s)',
                      n.nspname, c.relname, a.attname, t.typname),
               ', '
           )
      INTO offending
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_type t ON t.oid = a.atttypid
      LEFT JOIN pg_type bt ON bt.oid = t.typbasetype
      LEFT JOIN protected_column_exemption e
             ON e.schema_name = n.nspname
            AND e.table_name = c.relname
            AND e.column_name = a.attname
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg\\_toast%'
       AND n.nspname NOT LIKE 'pg\\_temp%'
       AND c.relkind = 'r'
       AND a.attnum > 0
       AND NOT a.attisdropped
       -- by oid, not by name: a look-alike domain in another schema must not
       -- shadow public.ciphertext now that every schema is scanned
       AND a.atttypid <> 'public.ciphertext'::regtype
       AND COALESCE(t.typelem, 0) <> 'public.ciphertext'::regtype
       AND COALESCE(bt.typname, t.typname) IN ({type_names})
       AND e.column_name IS NULL;

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
            'DEC-0012: plaintext column on a stored table: %', offending
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
    schema_name text NOT NULL DEFAULT 'public',
    table_name text NOT NULL,
    column_name text NOT NULL,
    reason text NOT NULL CHECK (length(trim(reason)) > 0),
    decision_ref text NOT NULL,
    PRIMARY KEY (schema_name, table_name, column_name)
)
""",
            function,
            """
CREATE EVENT TRIGGER dec0012_no_plaintext_columns
    ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE', 'ALTER TABLE',
                 'CREATE TABLE AS', 'SELECT INTO')
    EXECUTE FUNCTION dec0012_reject_plaintext_columns()
""",
        )

    def install(self, connection: psycopg.Connection) -> None:
        """Apply the guard inside the caller-owned transaction."""
        with connection.cursor() as cursor:
            for statement in self._statements():
                cursor.execute(statement)
            for exemption in self._exemptions():
                cursor.execute(
                    """
                    INSERT INTO protected_column_exemption (
                        schema_name, table_name, column_name,
                        reason, decision_ref
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        exemption.schema_name,
                        exemption.table_name,
                        exemption.column_name,
                        exemption.reason,
                        exemption.decision_ref,
                    ),
                )
