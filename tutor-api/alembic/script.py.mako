"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    # Statements belong on a class under adapters/persistence/schema.py and run
    # through MigrationSession; a migration body holds no SQL of its own.
    raise NotImplementedError


def downgrade() -> None:
    raise NotImplementedError
