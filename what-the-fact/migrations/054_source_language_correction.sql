-- 054: correct the declared language of two French sources (task #5749).
--
-- La Presse (491) and Le Journal de Montréal (13765) publish in FRENCH but were
-- declared language='en'. consumer/routes.py builds the public /divergence
-- EN-vs-FR comparison with
--     COUNT(*) FILTER (WHERE s.language = 'en') ... FILTER (WHERE s.language = 'fr')
-- so 2,534 French articles were being counted on the ENGLISH side of a bias
-- comparison whose entire premise is that the two sides are different languages.
-- On a fact-checking product that is not a cosmetic mislabel: it silently
-- corrupts a published finding.
--
-- IDENTIFIED BY CONTENT, NOT BY NAME. Measured over article titles:
--
--   id    source                  declared  articles  FR-stopword%  accented%
--   491   La Presse               en             180        97.2       18.9
--   13765 Le Journal de Montréal  en           2,354        88.8       93.4
--   13766 L'actualité             en             251        77.7       74.9
--   592   Le Devoir               fr           4,084        87.5       81.0   (control, correct)
--   591   Radio-Canada            fr           3,115        90.2       86.3   (control, correct)
--   13758 Edmonton Journal        en           1,142         0.0        0.1   (control, correct)
--
-- "Edmonton Journal" matches a French-sounding-name heuristic and is an ENGLISH
-- paper. A rename-by-name sweep would have mislabelled it in the other
-- direction — which is why this migration lists two explicit ids rather than
-- running a pattern.
--
-- Reversible: set language='en' for the same two ids.

UPDATE wtf.sources SET language = 'fr' WHERE id = 491    AND language = 'en';
UPDATE wtf.sources SET language = 'fr' WHERE id = 13765  AND language = 'en';
-- L'actualité was NOT in the original report. The verification block at the
-- bottom of this migration found it on the first run, which is the whole reason
-- that block exists: a fix that only repairs the rows someone happened to
-- notice leaves the same defect live under a different name.
UPDATE wtf.sources SET language = 'fr' WHERE id = 13766  AND language = 'en';

-- Fail LOUD if the corpus still disagrees with the labels: any source whose
-- titles are overwhelmingly French while declared English means a NEW source
-- arrived with the same defect. This is a check, not a fix — it names the row
-- rather than guessing at it.
DO $$
DECLARE
    offender RECORD;
BEGIN
    FOR offender IN
        SELECT s.id, s.name, s.language,
               round(100.0 * count(*) FILTER (
                   WHERE a.title ~ '[éèêàçûôîùâ]') / count(*), 1) AS pct_accented,
               count(*) AS arts
        FROM wtf.articles a
        JOIN wtf.sources s ON s.id = a.source_id
        GROUP BY s.id, s.name, s.language
        HAVING count(*) >= 100
           AND s.language = 'en'
           AND count(*) FILTER (WHERE a.title ~ '[éèêàçûôîùâ]')::float / count(*) > 0.5
    LOOP
        RAISE WARNING 'source % (%) is declared en but %%% of % titles carry French accents — check it',
            offender.id, offender.name, offender.pct_accented, offender.arts;
    END LOOP;
END $$;
