# Genealogy Module Feature Research
**Date**: 2026-04-06 | **Depth**: Standard

## Prioritized Feature List (by implementation value)

### Tier 1 -- High Impact, Proven Feasible

1. **GEDCOM Import/Export** -- Universal genealogy data exchange. Use `python-gedcom` (66 stars) or `gedcompy` (40 stars) for Python parsing. GEDCOM 7.0 is the modern standard (JSON-friendly, replaces 5.5.1). Non-negotiable for interop with every other platform.

2. **AI Record Hints** -- Ancestry's killer feature ("ThruLines"): cross-reference user tree against public records and suggest connections. Implementable with FamilySearch API + Chronicling America + OpenLibrary genealogy collections. Bridge dispatcher routes AI matching.

3. **Photo Colorization + Restoration** -- MyHeritage's "Deep Nostalgia" / photo colorize went viral. Use DeepAI colorization API or self-host `DeOldify` (GitHub, 18k+ stars, not in genealogy search but well-known). Route through ComfyUI with restoration models.

4. **Multiple Visualization Modes**:
   - **Pedigree chart** (ancestor-focused, binary tree expanding left)
   - **Descendant chart** (top-down from ancestor)
   - **Fan chart** (radial/semicircle, compact for many generations)
   - **Timeline view** (life events on horizontal axis)
   - Use `BALKANGraph/FamilyTreeJS` (87 stars, commercial) or build with D3.js `d3-dag` for DAG layouts (handles pedigree collapse). Gramps uses GraphViz for server-side rendering.

5. **DNA Integration Dashboard** -- Display ethnicity estimates, shared DNA segments, relative matching. No API needed initially; let users upload raw DNA files (23andMe/AncestryDNA CSV format) and parse locally. AI can flag potential matches within the platform.

### Tier 2 -- Medium Impact, Worth Adding

6. **Handwriting/OCR Transcription** -- Historical document digitization. Use Tesseract OCR for printed text; for cursive handwriting, HTR models like `TrOCR` (Microsoft, Hugging Face) or Transkribus API. Bridge-dispatched with specialized agent.

7. **Additional Data Sources** (beyond what you already have):
   - **Find A Grave API** -- cemetery/burial records (findagrave.com, owned by Ancestry)
   - **OpenArchives.org** -- Dutch/European archives aggregator
   - **BillionGraves** -- GPS-tagged headstone photos with API
   - **GeneaNet** -- European genealogy database (has API)
   - **Internet Archive / Wayback** -- historical newspaper OCR
   - **Ellis Island / Castle Garden** -- US immigration (free, scrapeable)
   - **UK National Archives Discovery API** -- British historical records
   - **DPLA (Digital Public Library of America)** -- aggregated US collections API

8. **Smart Merge / Deduplication** -- AI-powered detection of duplicate persons across imported trees. FamilySearch calls this "Record Hints." Use embedding similarity on person+event data.

9. **Relationship Calculator** -- "How am I related to X?" with path-finding algorithm. WikiTree does this well. Simple BFS/DFS on the family graph.

### Tier 3 -- Differentiators

10. **AI Story Generation** -- Given a person's life events, dates, locations, generate a narrative biography. Bridge dispatch to LLM with structured prompt. Ancestry calls this "LifeStory."

11. **Map Timeline** -- Animate family migration on a map over time (Leaflet.js + time slider). MyHeritage has this.

12. **Source Citation Manager** -- Proper genealogical source citations (Evidence Explained format). Critical for serious genealogists.

13. **Collaborative Trees** -- Multiple users editing one tree with conflict resolution. WikiTree's model.

## Open Source Tools Worth Integrating

| Tool | Stars | Language | Use Case |
|------|-------|----------|----------|
| webtrees | 740 | PHP | Reference for feature completeness |
| python-gedcom | 66 | Python | GEDCOM 5.5.1 parsing |
| gedcompy | 40 | Python | Alternative GEDCOM parser |
| tmcw/gedcom | 183 | TypeScript | Client-side GEDCOM to JSON |
| Gramps | N/A | Python/GTK | Desktop reference (plugin architecture) |
| BALKANGraph/FamilyTreeJS | 87 | JS | Pedigree/org chart rendering |
| DeOldify | 18k+ | Python | Photo colorization |

## Key Takeaways

- GEDCOM import is table stakes; without it, no genealogist will adopt the platform
- Photo AI features (colorize, animate, restore) drive viral adoption -- MyHeritage proved this
- Visualization variety matters: fan charts and timelines differentiate from basic tree views
- The biggest gap in open-source genealogy is AI-powered record matching; building this with Bridge dispatch would be a genuine differentiator
- DNA features can start with file upload/parse, no lab partnership needed
