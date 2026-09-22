"""Apply the encryption guard and the reviewed schema statements."""

from typing import cast

import psycopg
from alembic import op

from tutor_api.adapters.persistence.encryption_at_rest import EncryptionAtRestSchema


class MigrationSession:
    """Run schema statements on the Alembic connection."""

    def install_guard(self) -> None:
        EncryptionAtRestSchema().install(self._driver())

    def execute(self, statements: tuple[str, ...]) -> None:
        for statement in statements:
            op.execute(statement)

    def _driver(self) -> psycopg.Connection:
        bind = op.get_bind()
        return cast(psycopg.Connection, bind.connection.driver_connection)
