-- Which knowledge zones an account may enter (2026-11-23). Set by a KM admin. An account without rows holds no zone.
-- Explicit DBA migration, like the other KM Control tables. Nothing reads this table unless KM_ZONE_ACL_ENFORCE is on.
CREATE TABLE IF NOT EXISTS km_user_zones (
    user_id    TEXT NOT NULL REFERENCES km_users(user_id) ON DELETE CASCADE,
    zone_id    TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    granted_at BIGINT NOT NULL,
    PRIMARY KEY (user_id, zone_id)
);
