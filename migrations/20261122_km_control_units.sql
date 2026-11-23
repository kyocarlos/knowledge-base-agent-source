-- Organisation units for document permissions (2026-11-22). The unit list is CSIT's (KM imports it); membership is set by a KM admin.
-- Explicit DBA migration, like the other KM Control tables. Nothing reads these tables unless KM_ZONE_ACL_ENFORCE is on.
CREATE TABLE IF NOT EXISTS km_units (
    unit_code   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    source      TEXT NOT NULL DEFAULT 'csit',
    imported_by TEXT NOT NULL,
    updated_at  BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS km_user_units (
    user_id     TEXT NOT NULL REFERENCES km_users(user_id) ON DELETE CASCADE,
    unit_code   TEXT NOT NULL REFERENCES km_units(unit_code),
    assigned_by TEXT NOT NULL,
    assigned_at BIGINT NOT NULL,
    PRIMARY KEY (user_id, unit_code)
);
CREATE INDEX IF NOT EXISTS km_user_units_unit_idx ON km_user_units(unit_code);
