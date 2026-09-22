"""The audit grant follows POSTGRES_APP_USER, and the name cannot carry SQL."""

import pytest

from tutor_api.adapters.persistence.schema import ApplicationRole, AuditSchema
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
