-- Per-user, per-lane terminal access grants (#6700).
--
-- Owner decision 2026-09-11: "explicit per-user allowlist". Until now a terminal
-- lane was admin-only, and that was only true by accident of the login path —
-- on_sso_login discards any session whose role != 'admin', so no non-admin session
-- exists to test. The archie-tui lane is meant for approved human staff who are NOT
-- full platform admins, which needs a rule the terminal code states itself.
--
-- SHAPE: a grant is (user, lane). Admins are NOT listed here — they are allowed by
-- role, and adding them would create two sources of truth for the same answer.
-- Revocation is a timestamp, not a DELETE, so "who could reach the host shell last
-- Tuesday" stays answerable. A shell is exactly the thing you want an audit trail on.
CREATE TABLE IF NOT EXISTS terminal_lane_grants (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    lane        TEXT    NOT NULL,
    granted_by  INTEGER,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ,
    revoked_by  INTEGER,
    note        TEXT
);

-- One LIVE grant per (user, lane). A partial unique index rather than a plain one,
-- so a user can be granted -> revoked -> granted again and keep the full history.
CREATE UNIQUE INDEX IF NOT EXISTS uq_lane_grant_live
    ON terminal_lane_grants (user_id, lane)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_lane_grants_lookup
    ON terminal_lane_grants (user_id, lane)
    WHERE revoked_at IS NULL;

COMMENT ON TABLE terminal_lane_grants IS
    'Explicit per-user access to a coder terminal lane (#6700). Admins are allowed '
    'by ROLE and are deliberately not listed here. Revocation is a timestamp, never '
    'a delete, so historical access to a host shell stays auditable.';
