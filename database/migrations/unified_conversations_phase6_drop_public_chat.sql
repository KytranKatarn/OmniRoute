-- Phase 6 of the chat_* → unified_* migration (#2178).
-- Drops public.chat_conversations + public.chat_messages.
--
-- Safe because:
-- - platform_v2/tools/archie_chat migrated in Phase 4 (PR #190)
-- - archie-comms migrated in Phases 2+3 (PR #189)
-- - KBS uses tenant-scoped chat tables (tenant_N.chat_*), never public.chat_*
--   Verified in Phase 5 audit (2026-04-19): every KBS call to chat_* is preceded
--   by set_tenant_search_path(cur, tenant_id) in core/chat_manager.py and
--   plugins/kbs_communications/routes.py — schema shape completely differs
--   (visitor_name/channel/sender_type vs user_id/title/agent_target).
-- - All public row data was copied into public.unified_* across Phases 2 + 4 + 6
--   catch-up (final unmigrated count = 0 before this drop).
--
-- Idempotent via DROP TABLE IF EXISTS.
-- CASCADE drops chat_messages FK constraint + any dependent views/triggers
-- (all of which would be dead code at this point).

DROP TABLE IF EXISTS public.chat_messages CASCADE;
DROP TABLE IF EXISTS public.chat_conversations CASCADE;
