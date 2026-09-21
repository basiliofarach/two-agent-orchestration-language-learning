#!/bin/bash
set -euo pipefail

# POSTGRES_USER owns migrations. The application role is deliberately distinct;
# BE-06 grants its audit-table INSERT/SELECT permissions.
psql --set ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;

DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT FROM pg_roles WHERE rolname = '${POSTGRES_APP_USER}'
  ) THEN
    CREATE ROLE ${POSTGRES_APP_USER}
      LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
  END IF;
END
\$\$;
SQL
