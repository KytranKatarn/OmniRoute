-- 468: Terry (agent 377) LinkedIn social profile row + identity uniqueness
--
-- WHY (#5644): S.I.G.N.A.L. is being taught to ground Terry's drafting voice in his real
-- LinkedIn profile. The profile capture resolves WHICH URL to read from
-- `agent_social_profiles` rather than hardcoding it -- but Terry had NO row at all
-- (measured 2026-08-16: 35 rows, agent 342 has linkedin, 377 has nothing), so the
-- capture had nothing to resolve.
--
-- The UNIQUE index is load-bearing, not hygiene: two linkedin rows for one agent makes
-- "which profile is Terry's" ambiguous, and the loser of that coin-flip would be ingested
-- into Chronicle as his authored voice corpus. A mislabelled voice corpus is the
-- "wrong result that looks right" class (ADR-027) -- so the ambiguity is made
-- impossible at the schema level instead of being handled by ORDER BY luck.
-- Verified 0 existing duplicate (agent_id, platform) pairs before adding.

CREATE UNIQUE INDEX IF NOT EXISTS agent_social_profiles_agent_platform_uniq
    ON public.agent_social_profiles (agent_id, platform);

-- Idempotent insert. Deliberately NOT an upsert of profile_url: if a human later
-- corrects the URL by hand, re-running this migration must not silently revert it.
INSERT INTO public.agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT 377, 'linkedin', 'terry-caetano-8506381a',
       'https://linkedin.com/in/terry-caetano-8506381a', TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM public.agent_social_profiles
     WHERE agent_id = 377 AND platform = 'linkedin'
);
