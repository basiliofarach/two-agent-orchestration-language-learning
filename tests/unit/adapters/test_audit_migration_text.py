"""Audit migrations do not themselves update or delete the log."""

import re
from pathlib import Path


class AuditMigrationText:
    def mutations(self, source: str) -> tuple[str, ...]:
        pattern = re.compile(
            r"(?im)^\s*(update|delete\s+from)\s+(public\.)?"
            r"(turn_audit|gate_evaluation)\b"
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

    def test_scanner_flags_a_mutation(self) -> None:
        found = AuditMigrationText().mutations(
            "UPDATE turn_audit SET record_hash = 'x'"
        )
        assert found == ("UPDATE turn_audit",)
