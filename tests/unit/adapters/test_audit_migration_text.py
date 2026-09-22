"""Audit migrations do not themselves update or delete the log."""

import re
from pathlib import Path

from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    AuditSchema,
    AuditSchemaUpgrade,
)


class AuditMigrationText:
    def mutations(self, source: str) -> tuple[str, ...]:
        pattern = re.compile(
            r"(?im)^\s*(update|delete\s+from)\s+(public\.)?"
            r"(turn_audit|gate_evaluation|turn_citation|human_action)\b"
        )
        return tuple(match.group(0) for match in pattern.finditer(source))


class TestAuditMigrationsDoNotMutate:
    def test_revisions_issue_no_update_or_delete(self) -> None:
        root = (
            Path(__file__).resolve().parents[3] / "tutor-api" / "alembic" / "versions"
        )
        sources = tuple(sorted(root.glob("*.py")))
        assert sources
        scanner = AuditMigrationText()
        for path in sources:
            assert scanner.mutations(path.read_text(encoding="utf-8")) == ()

    def test_audit_schema_statements_issue_no_update_or_delete(self) -> None:
        schema = AuditSchema(ApplicationRole("tutor_app"))
        source = "\n".join(schema.statements())
        assert "UNIQUE (session_id, turn_index)" in source
        assert AuditMigrationText().mutations(source) == ()

    def test_audit_upgrade_issues_no_update_or_delete(self) -> None:
        upgrade = AuditSchemaUpgrade(ApplicationRole("tutor_app"))
        scanner = AuditMigrationText()
        assert scanner.mutations("\n".join(upgrade.statements())) == ()
        assert scanner.mutations("\n".join(upgrade.downgrade_statements())) == ()
        source = "\n".join(upgrade.statements())
        assert "INSERT INTO turn_citation" in source
        assert "INSERT INTO protected_column_exemption" in source
        assert "'human_action', 'action'" in source

    def test_scanner_flags_a_mutation(self) -> None:
        found = AuditMigrationText().mutations(
            "UPDATE turn_audit SET record_hash = 'x'"
        )
        assert found == ("UPDATE turn_audit",)
