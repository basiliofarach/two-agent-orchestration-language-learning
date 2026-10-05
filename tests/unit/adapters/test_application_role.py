"""The audit grant follows POSTGRES_APP_USER, and the name cannot carry SQL."""

import pytest

from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    AuditSchema,
    RequestPathPrivileges,
)
from tutor_api.settings import ApplicationSettings


class TestApplicationRole:
    def test_settings_default_is_tutor_app(self) -> None:
        settings = ApplicationSettings(postgres_app_user="tutor_app")
        assert settings.postgres_app_user == "tutor_app"

    def test_quotes_the_name_for_both_sql_positions(self) -> None:
        role = ApplicationRole("audit_writer")
        assert role.identifier() == '"audit_writer"'
        assert role.literal() == "'audit_writer'"

    @pytest.mark.parametrize(
        "name",
        [
            'tutor_app"; DROP TABLE turn_audit;--',
            "tutor_app'; DROP TABLE turn_audit;--",
            "tutor app",
            "9lives",
            "-",
        ],
    )
    def test_rejects_a_name_that_is_not_an_identifier(self, name: str) -> None:
        with pytest.raises(ValueError, match="not a usable role name"):
            ApplicationRole(name)


class TestAuditSchemaGrantsTheConfiguredRole:
    def test_grants_name_the_configured_role_only(self) -> None:
        role = ApplicationRole("audit_writer")
        statements = AuditSchema(role).statements()
        grants = tuple(s for s in statements if "GRANT INSERT, SELECT" in s)
        assert grants
        for statement in grants:
            assert '"audit_writer"' in statement
            assert "tutor_app" not in statement

    def test_role_existence_check_uses_a_string_literal(self) -> None:
        role = ApplicationRole("audit_writer")
        creation = AuditSchema(role).statements()[0]
        assert "rolname = 'audit_writer'" in creation
        assert 'CREATE ROLE "audit_writer" NOLOGIN' in creation


class TestRequestPathPrivileges:
    def test_grants_select_on_the_request_path_tables_only(self) -> None:
        role = ApplicationRole("audit_writer")
        statements = RequestPathPrivileges(role).statements()
        granted = tuple(statement for statement in statements if "GRANT " in statement)
        assert granted == (
            'GRANT SELECT ON TABLE policy_version TO "audit_writer"',
            'GRANT SELECT ON TABLE kb_document TO "audit_writer"',
            'GRANT SELECT ON TABLE kb_chunk TO "audit_writer"',
        )
        assert all("INSERT" not in statement for statement in granted)
        assert all("tutor_app" not in statement for statement in statements)

    def test_downgrade_revokes_select_and_does_not_drop_the_tables(self) -> None:
        privileges = RequestPathPrivileges(ApplicationRole("audit_writer"))
        statements = privileges.downgrade_statements()
        assert statements == (
            'REVOKE SELECT ON TABLE policy_version FROM "audit_writer"',
            'REVOKE SELECT ON TABLE kb_document FROM "audit_writer"',
            'REVOKE SELECT ON TABLE kb_chunk FROM "audit_writer"',
        )
        assert all("DROP" not in statement for statement in statements)
