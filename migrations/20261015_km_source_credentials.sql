-- KM Control PostgreSQL; explicit management-channel migration.
-- Runtime initialization MUST NOT execute DDL. Existing auth tables are not changed.
-- Stores sealed per-user Confluence/Jira/TestRail credentials. The table never
-- holds plaintext; envelopes are readable only by the CrossSearch worker key.
BEGIN;
CREATE TABLE IF NOT EXISTS km_source_credentials (
 user_id text NOT NULL REFERENCES km_users(user_id) ON DELETE CASCADE,
 source text NOT NULL CHECK(source IN ('confluence','jira','testrail')),
 source_username text NOT NULL CHECK(char_length(source_username) BETWEEN 1 AND 256),
 auth_type text NOT NULL CHECK(auth_type IN ('basic','bearer')),
 secret_envelope text NOT NULL CHECK(secret_envelope LIKE 'km-src-cred-v1.%'),
 key_id text NOT NULL,
 status text NOT NULL CHECK(status IN ('active','invalid')),
 last_error_code text,
 last_verified_at bigint,
 created_at bigint NOT NULL,
 updated_at bigint NOT NULL,
 PRIMARY KEY(user_id, source)
);
CREATE TABLE IF NOT EXISTS km_control_schema_migrations (version TEXT PRIMARY KEY, applied_at BIGINT NOT NULL);
INSERT INTO km_control_schema_migrations(version,applied_at) VALUES('20261015_km_source_credentials',EXTRACT(EPOCH FROM now())::BIGINT) ON CONFLICT(version) DO NOTHING;
COMMIT;
