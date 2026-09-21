#!/bin/bash
set -euo pipefail

# POSTGRES_USER owns migrations. The application role is deliberately distinct;
# BE-06 grants its audit-table INSERT/SELECT permissions. The role name and
# password are psql variables: :'…' quotes a literal and :"…" quotes an
# identifier, so a quote in either value cannot change the statement.
psql --set ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_user="$POSTGRES_APP_USER" \
  --set=app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

SELECT EXISTS (
  SELECT FROM pg_roles WHERE rolname = :'app_user'
) AS app_role_exists
\gset

\if :app_role_exists
\else
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
\endif
SQL
