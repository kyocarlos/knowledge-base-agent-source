-- KM Control PostgreSQL; explicit management-channel migration.
-- Runtime initialization MUST NOT execute DDL. Existing auth tables are not changed.
-- Per-account, per-instance capabilities (for example "may switch the WiFi scheduled-summary notification").
-- The capability ids come from config/km_capabilities.json, so no CHECK on them here: adding one needs no migration.
BEGIN;
CREATE TABLE IF NOT EXISTS km_capability_grants (
 user_id text NOT NULL REFERENCES km_users(user_id) ON DELETE CASCADE,
 instance_id text NOT NULL CHECK(char_length(instance_id) BETWEEN 1 AND 64),
 capability text NOT NULL CHECK(char_length(capability) BETWEEN 1 AND 128),
 active boolean NOT NULL DEFAULT TRUE,
 approved_by text NOT NULL,
 approved_at bigint NOT NULL,
 updated_at bigint NOT NULL,
 PRIMARY KEY(user_id, instance_id, capability)
);
CREATE TABLE IF NOT EXISTS km_control_schema_migrations (version TEXT PRIMARY KEY, applied_at BIGINT NOT NULL);
INSERT INTO km_control_schema_migrations(version,applied_at) VALUES('20261021_km_capability_grants',EXTRACT(EPOCH FROM now())::BIGINT) ON CONFLICT(version) DO NOTHING;
COMMIT;
