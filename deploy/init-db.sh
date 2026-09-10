#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
CREATE ROLE forget_lah_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE forget_lah TO forget_lah_app;
GRANT USAGE ON SCHEMA public TO forget_lah_app;
ALTER DEFAULT PRIVILEGES FOR ROLE forget_lah_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO forget_lah_app;
ALTER DEFAULT PRIVILEGES FOR ROLE forget_lah_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO forget_lah_app;
CREATE DATABASE forget_lah_test OWNER forget_lah_app;
SQL
