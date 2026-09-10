-- 483 — bind a terminal auth token to the lane it may open.
--
-- scripts/ttyd_auth_proxy.py fronts BOTH coder lanes. The two running instances differ
-- ONLY by environment (PROXY_PORT/TTYD_PORT) and consult THIS table:
--
--     claude: :7681 -> 127.0.0.1:17681   the HOST tmux session, no container boundary
--     codex:  :7683 -> 127.0.0.1:17682   container archie_codex_terminal, --max-clients 1
--
-- Without a lane column the proxy looked a token up by value alone, so a token minted for
-- the SANDBOXED codex lane was accepted by the claude HOST-shell proxy, and the reverse.
-- Every visible boundary between the two (separate units, ports, upstreams, containers)
-- said "two systems"; the one thing they shared — the authority they consult — is the one
-- that mattered.
--
-- NULL is deliberately left as the default rather than backfilled: the proxy FAILS CLOSED
-- on a NULL lane. Existing rows are one-time and expire in five minutes, so refusing them
-- costs nothing and is safer than guessing which lane a legacy token was meant for.

ALTER TABLE terminal_auth_tokens ADD COLUMN IF NOT EXISTS lane TEXT;

CREATE INDEX IF NOT EXISTS idx_term_tokens_lane ON terminal_auth_tokens (lane);

COMMENT ON COLUMN terminal_auth_tokens.lane IS
  'Lane this token may open (claude|codex). NULL fails closed at the proxy: both lanes '
  'share one table and one script, so an unbound token would open either one.';
