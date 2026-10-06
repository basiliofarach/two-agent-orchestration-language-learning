"""The audit grant follows POSTGRES_APP_USER, and the name cannot carry SQL."""

import pytest

from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    AuditSchema,
    LearnerHistoryColumnGrant,
    LearnerHistoryEventIdGrant,
    RequestPathPrivileges,
    TurnAuditOpenSession,
    TutoringSessionColumnGrant,
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


class TestLearnerHistoryColumnGrant:
    def test_grants_select_on_named_columns_and_never_the_pseudonym(self) -> None:
        statements = LearnerHistoryColumnGrant(
            ApplicationRole("audit_writer")
        ).statements()
        assert statements == (
            'REVOKE ALL ON TABLE learner FROM PUBLIC, "audit_writer"',
            "GRANT SELECT (learner_id, retain_until, proficiency_level) "
            'ON TABLE learner TO "audit_writer"',
            'REVOKE ALL ON TABLE learner_history_event FROM PUBLIC, "audit_writer"',
            "GRANT SELECT (learner_id, item_id, correct, occurred_at, id) "
            'ON TABLE learner_history_event TO "audit_writer"',
        )
        assert all("pseudonym" not in statement for statement in statements)

    def test_downgrade_revokes_the_columns_by_name(self) -> None:
        downgrade = LearnerHistoryColumnGrant(
            ApplicationRole("audit_writer")
        ).downgrade_statements()
        assert downgrade == (
            "REVOKE SELECT (learner_id, retain_until, proficiency_level) "
            'ON TABLE learner FROM "audit_writer"',
            "REVOKE SELECT (learner_id, item_id, correct, occurred_at, id) "
            'ON TABLE learner_history_event FROM "audit_writer"',
        )


class TestSessionAndEventIdGrants:
    def test_the_session_grant_is_three_columns_and_not_the_tutor(self) -> None:
        statements = TutoringSessionColumnGrant(
            ApplicationRole("audit_writer")
        ).statements()
        assert statements == (
            'REVOKE ALL ON TABLE tutoring_session FROM PUBLIC, "audit_writer"',
            "GRANT SELECT (id, learner_id, stopped_at) "
            'ON TABLE tutoring_session TO "audit_writer"',
        )
        assert all("tutor_id" not in statement for statement in statements)
        assert all("stop_reason" not in statement for statement in statements)
        assert TutoringSessionColumnGrant(
            ApplicationRole("audit_writer")
        ).downgrade_statements() == (
            "REVOKE SELECT (id, learner_id, stopped_at) "
            'ON TABLE tutoring_session FROM "audit_writer"',
        )

    def test_the_event_id_repair_grants_id_and_its_downgrade_is_empty(self) -> None:
        role = ApplicationRole("audit_writer")
        assert LearnerHistoryEventIdGrant(role).statements() == (
            'GRANT SELECT (id) ON TABLE learner_history_event TO "audit_writer"',
        )
        assert LearnerHistoryEventIdGrant(role).downgrade_statements() == ()


class TestTurnAuditOpenSession:
    def test_the_trigger_locks_the_session_row_and_refuses_a_stopped_one(
        self,
    ) -> None:
        statements = TurnAuditOpenSession().statements()
        joined = " ".join(statements)
        assert "SECURITY DEFINER" in joined
        assert "SET search_path = pg_catalog, public" in joined
        assert "FOR SHARE" in joined
        assert "SELECT stopped_at INTO stopped" in joined
        assert "IF stopped IS NOT NULL THEN" in joined
        assert f"ERRCODE = '{TurnAuditOpenSession.SQLSTATE}'" in joined
        assert "BEFORE INSERT ON turn_audit" in joined
        assert (
            "REVOKE ALL ON FUNCTION reject_turn_in_stopped_session() FROM PUBLIC"
            in statements
        )
        assert all("tutor_id" not in statement for statement in statements)

    def test_the_downgrade_drops_the_trigger_then_the_function(self) -> None:
        assert TurnAuditOpenSession().downgrade_statements() == (
            "DROP TRIGGER IF EXISTS turn_audit_open_session ON turn_audit",
            "DROP FUNCTION IF EXISTS reject_turn_in_stopped_session()",
        )
