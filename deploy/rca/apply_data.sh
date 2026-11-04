#!/bin/bash
# RCA data + read-only role on the TEST plane TimescaleDB (kb-timescaledb / kb_timeseries). Atomic data load, then a SELECT-only role.
set -euo pipefail
D=$HOME/.km-control/rca-deploy-20261104
PSQL="docker exec -i kb-timescaledb psql -U kb_timeseries -d kb_timeseries -v ON_ERROR_STOP=1 -q"
before=$($PSQL -Atc "select coalesce((select count(*) from km_test.test_run),0)" 2>/dev/null || echo "schema-missing")
echo "test_run rows before: $before"
# 1. schema (IF NOT EXISTS) + data (ON CONFLICT DO NOTHING) in one transaction: either everything or nothing
cat $D/schema.sql $D/km_test_data.sql | docker exec -i kb-timescaledb psql -U kb_timeseries -d kb_timeseries -v ON_ERROR_STOP=1 --single-transaction -q
echo "test_run rows after:  $($PSQL -Atc 'select count(*) from km_test.test_run')"
# 2. read-only role
PW=$(head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 32)
$PSQL <<SQL
SELECT 'CREATE ROLE km_rca_ro LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='km_rca_ro') \gexec
ALTER ROLE km_rca_ro PASSWORD '$PW' CONNECTION LIMIT 8;
ALTER ROLE km_rca_ro SET default_transaction_read_only = on;
ALTER ROLE km_rca_ro SET statement_timeout = '15s';
GRANT CONNECT ON DATABASE kb_timeseries TO km_rca_ro;
GRANT USAGE ON SCHEMA km_test TO km_rca_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA km_test TO km_rca_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA km_test GRANT SELECT ON TABLES TO km_rca_ro;
SQL
# 3. DSN file for the web container (0600, never printed)
( umask 077; printf 'postgresql://km_rca_ro:%s@kb-timescaledb:5432/kb_timeseries\n' "$PW" > $D/km-rca-dsn )
chmod 644 $D/km-rca-dsn   # the container user must read the bind-mounted file; the folder is 0700-parented under .km-control (0700)
# 4. prove the role can read and cannot write
export PGPASSWORD="$PW"
R="docker exec -e PGPASSWORD kb-timescaledb psql -h 127.0.0.1 -U km_rca_ro -d kb_timeseries -v ON_ERROR_STOP=0 -Atq"
echo "role read:   $($R -c 'select count(*) from km_test.test_run')"
echo "role write:  $($R -c "insert into km_test.metric_dictionary(metric_name,unit,kind) values('x','x','measured')" 2>&1 | tr '\n' ' ' | cut -c1-110)"
echo "role other:  $($R -c 'select count(*) from pg_tables where schemaname not in ($$km_test$$,$$pg_catalog$$,$$information_schema$$)' 2>&1 | cut -c1-80)"
echo done
