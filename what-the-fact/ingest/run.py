"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import datetime
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine, text

from ingest.sources.cbc_english import fetch_articles as cbc_fetch, SOURCE_SLUG as CBC_SLUG, CBC_URL
from ingest.sources.global_news import fetch_articles as global_news_fetch, SOURCE_SLUG as GLOBAL_NEWS_SLUG, GLOBAL_NEWS_URL
from ingest.sources.ctv_news import fetch_articles as ctv_fetch, SOURCE_SLUG as CTV_SLUG, SOURCE_NAME as CTV_NAME, SOURCE_URL as CTV_URL, RSS_URL as CTV_RSS, BIAS_LEAN as CTV_BIAS
from ingest.sources.toronto_star import fetch_articles as star_fetch, SOURCE_SLUG as STAR_SLUG, SOURCE_NAME as STAR_NAME, SOURCE_URL as STAR_URL, RSS_URL as STAR_RSS, BIAS_LEAN as STAR_BIAS
from ingest.sources.national_post import fetch_articles as np_fetch, SOURCE_SLUG as NP_SLUG, SOURCE_NAME as NP_NAME, SOURCE_URL as NP_URL, RSS_URL as NP_RSS, BIAS_LEAN as NP_BIAS
from ingest.sources.globe_mail import fetch_articles as gm_fetch, SOURCE_SLUG as GM_SLUG, SOURCE_NAME as GM_NAME, SOURCE_URL as GM_URL, RSS_URL as GM_RSS, BIAS_LEAN as GM_BIAS
from ingest.sources.ipolitics import fetch_articles as ipo_fetch, SOURCE_SLUG as IPO_SLUG, SOURCE_NAME as IPO_NAME, SOURCE_URL as IPO_URL, RSS_URL as IPO_RSS, BIAS_LEAN as IPO_BIAS
from ingest.sources.the_narwhal import fetch_articles as narwhal_fetch, SOURCE_SLUG as NARWHAL_SLUG, SOURCE_NAME as NARWHAL_NAME, SOURCE_URL as NARWHAL_URL, RSS_URL as NARWHAL_RSS, BIAS_LEAN as NARWHAL_BIAS
from ingest.sources.la_presse import fetch_articles as lp_fetch, SOURCE_SLUG as LP_SLUG, SOURCE_NAME as LP_NAME, SOURCE_URL as LP_URL, RSS_URL as LP_RSS, BIAS_LEAN as LP_BIAS
from ingest.sources.canadaland import fetch_articles as cl_fetch, SOURCE_SLUG as CL_SLUG, SOURCE_NAME as CL_NAME, SOURCE_URL as CL_URL, RSS_URL as CL_RSS, BIAS_LEAN as CL_BIAS
from ingest.sources.radio_canada import fetch_articles as rc_fetch, SOURCE_SLUG as RC_SLUG, SOURCE_NAME as RC_NAME, SOURCE_URL as RC_URL, RSS_URL as RC_RSS, BIAS_LEAN as RC_BIAS
from ingest.sources.le_devoir import fetch_articles as ld_fetch, SOURCE_SLUG as LD_SLUG, SOURCE_NAME as LD_NAME, SOURCE_URL as LD_URL, RSS_URL as LD_RSS, BIAS_LEAN as LD_BIAS
from ingest.sources.vancouver_sun import fetch_articles as vs_fetch, SOURCE_SLUG as VS_SLUG, SOURCE_NAME as VS_NAME, SOURCE_URL as VS_URL, RSS_URL as VS_RSS, BIAS_LEAN as VS_BIAS
# montreal_gazette / saskatoon_starphoenix / regina_leaderpost moved to the
# DB-driven sitemap path (#4909) — Postmedia removed their RSS feeds; their
# wtf.sources.rss_feed now carries a 'sitemap:' URL (migration 048).
from ingest.sources.ottawa_citizen import fetch_articles as oc_fetch, SOURCE_SLUG as OC_SLUG, SOURCE_NAME as OC_NAME, SOURCE_URL as OC_URL, RSS_URL as OC_RSS, BIAS_LEAN as OC_BIAS
from ingest.sources.calgary_herald import fetch_articles as ch_fetch, SOURCE_SLUG as CH_SLUG, SOURCE_NAME as CH_NAME, SOURCE_URL as CH_URL, RSS_URL as CH_RSS, BIAS_LEAN as CH_BIAS
from ingest.sources.edmonton_journal import fetch_articles as ej_fetch, SOURCE_SLUG as EJ_SLUG, SOURCE_NAME as EJ_NAME, SOURCE_URL as EJ_URL, RSS_URL as EJ_RSS, BIAS_LEAN as EJ_BIAS
from ingest.sources.winnipeg_free_press import fetch_articles as wp_fetch, SOURCE_SLUG as WP_SLUG, SOURCE_NAME as WP_NAME, SOURCE_URL as WP_URL, RSS_URL as WP_RSS, BIAS_LEAN as WP_BIAS
from ingest.sources.the_tyee import fetch_articles as tt_fetch, SOURCE_SLUG as TT_SLUG, SOURCE_NAME as TT_NAME, SOURCE_URL as TT_URL, RSS_URL as TT_RSS, BIAS_LEAN as TT_BIAS
from ingest.sources.ricochet_media import fetch_articles as rm_fetch, SOURCE_SLUG as RM_SLUG, SOURCE_NAME as RM_NAME, SOURCE_URL as RM_URL, RSS_URL as RM_RSS, BIAS_LEAN as RM_BIAS
from ingest.sources.financial_post import fetch_articles as fp_fetch, SOURCE_SLUG as FP_SLUG, SOURCE_NAME as FP_NAME, SOURCE_URL as FP_URL, RSS_URL as FP_RSS, BIAS_LEAN as FP_BIAS
from ingest.sources.journal_de_montreal import fetch_articles as jdm_fetch, SOURCE_SLUG as JDM_SLUG, SOURCE_NAME as JDM_NAME, SOURCE_URL as JDM_URL, RSS_URL as JDM_RSS, BIAS_LEAN as JDM_BIAS
from ingest.sources.lactualite import fetch_articles as la_fetch, SOURCE_SLUG as LA_SLUG, SOURCE_NAME as LA_NAME, SOURCE_URL as LA_URL, RSS_URL as LA_RSS, BIAS_LEAN as LA_BIAS
from ingest.sources.aptn_news import fetch_articles as aptn_fetch, SOURCE_SLUG as APTN_SLUG, SOURCE_NAME as APTN_NAME, SOURCE_URL as APTN_URL, RSS_URL as APTN_RSS, BIAS_LEAN as APTN_BIAS
from ingest.sources.bnn_bloomberg import fetch_articles as bnn_fetch, SOURCE_SLUG as BNN_SLUG, SOURCE_NAME as BNN_NAME, SOURCE_URL as BNN_URL, RSS_URL as BNN_RSS, BIAS_LEAN as BNN_BIAS
from ingest.sources.the_conversation_canada import fetch_articles as tcc_fetch, SOURCE_SLUG as TCC_SLUG, SOURCE_NAME as TCC_NAME, SOURCE_URL as TCC_URL, RSS_URL as TCC_RSS, BIAS_LEAN as TCC_BIAS
from ingest.sources.press_progress import fetch_articles as pp_fetch, SOURCE_SLUG as PP_SLUG, SOURCE_NAME as PP_NAME, SOURCE_URL as PP_URL, RSS_URL as PP_RSS, BIAS_LEAN as PP_BIAS
from ingest.sources.saltwire_news import fetch_articles as sw_fetch, SOURCE_SLUG as SW_SLUG, SOURCE_NAME as SW_NAME, SOURCE_URL as SW_URL, RSS_URL as SW_RSS, BIAS_LEAN as SW_BIAS
from ingest.normalizer import canonicalize
from ingest.bias import score_bias
from ingest.persist import upsert_article, record_failure, mark_ai_analyzed
from ingest.orchestrator import pick_priority_articles
from ingest.ai_dispatcher import analyze as ai_analyze
from ingest import (
    cluster_backlog_worker,
    factcheck_backlog_worker,
    geo_backlog_worker,
    llm_analysis_backlog_worker,
    scout_body_backlog_worker,
    bias_v2_backlog_worker,
    beat_backlog_worker,
    alerts_digest_worker,
    factcheck_partner_worker,
    weekly_digest_worker,
    newsletter_kbs_sync,
)
from shared.creed_events import emit as creed_emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wtf-ingest")
POLL_SECS = int(os.environ.get("WTF_POLL_SECS", "1800"))  # 30-min default for breaking news

# Source registry — (slug, name, site_url, rss_url, bias_lean, fetch_fn)
# Bias leans seeded from AllSides / Media Bias Fact Check, 2024 ratings.
SOURCES = [
    (CBC_SLUG,       "CBC English Top Stories",  "https://www.cbc.ca",              CBC_URL,        "center-left",  cbc_fetch),
    (GLOBAL_NEWS_SLUG, "Global News",             "https://globalnews.ca",           GLOBAL_NEWS_URL, "center",      global_news_fetch),
    (CTV_SLUG,       CTV_NAME,                   CTV_URL,                            CTV_RSS,        CTV_BIAS,       ctv_fetch),
    (STAR_SLUG,      STAR_NAME,                  STAR_URL,                           STAR_RSS,       STAR_BIAS,      star_fetch),
    (NP_SLUG,        NP_NAME,                    NP_URL,                             NP_RSS,         NP_BIAS,        np_fetch),
    (GM_SLUG,        GM_NAME,                    GM_URL,                             GM_RSS,         GM_BIAS,        gm_fetch),
    (IPO_SLUG,       IPO_NAME,                   IPO_URL,                            IPO_RSS,        IPO_BIAS,       ipo_fetch),
    (NARWHAL_SLUG,   NARWHAL_NAME,               NARWHAL_URL,                        NARWHAL_RSS,    NARWHAL_BIAS,   narwhal_fetch),
    (LP_SLUG,        LP_NAME,                    LP_URL,                             LP_RSS,         LP_BIAS,        lp_fetch),
    (CL_SLUG,        CL_NAME,                    CL_URL,                             CL_RSS,         CL_BIAS,        cl_fetch),
    (RC_SLUG,        RC_NAME,                    RC_URL,                             RC_RSS,         RC_BIAS,        rc_fetch),
    (LD_SLUG,        LD_NAME,                    LD_URL,                             LD_RSS,         LD_BIAS,        ld_fetch),
    (VS_SLUG,        VS_NAME,                    VS_URL,                             VS_RSS,         VS_BIAS,        vs_fetch),
    (OC_SLUG,        OC_NAME,                    OC_URL,                             OC_RSS,         OC_BIAS,        oc_fetch),
    # ── Expansion batch 2: regional, French-language, Indigenous, business ─────
    (CH_SLUG,        CH_NAME,                    CH_URL,                             CH_RSS,         CH_BIAS,        ch_fetch),
    (EJ_SLUG,        EJ_NAME,                    EJ_URL,                             EJ_RSS,         EJ_BIAS,        ej_fetch),
    (WP_SLUG,        WP_NAME,                    WP_URL,                             WP_RSS,         WP_BIAS,        wp_fetch),
    (TT_SLUG,        TT_NAME,                    TT_URL,                             TT_RSS,         TT_BIAS,        tt_fetch),
    (RM_SLUG,        RM_NAME,                    RM_URL,                             RM_RSS,         RM_BIAS,        rm_fetch),
    (FP_SLUG,        FP_NAME,                    FP_URL,                             FP_RSS,         FP_BIAS,        fp_fetch),
    (JDM_SLUG,       JDM_NAME,                   JDM_URL,                            JDM_RSS,        JDM_BIAS,       jdm_fetch),
    (LA_SLUG,        LA_NAME,                    LA_URL,                             LA_RSS,         LA_BIAS,        la_fetch),
    (APTN_SLUG,      APTN_NAME,                  APTN_URL,                           APTN_RSS,       APTN_BIAS,      aptn_fetch),
    (BNN_SLUG,       BNN_NAME,                   BNN_URL,                            BNN_RSS,        BNN_BIAS,       bnn_fetch),
    (TCC_SLUG,       TCC_NAME,                   TCC_URL,                            TCC_RSS,        TCC_BIAS,       tcc_fetch),
    (PP_SLUG,        PP_NAME,                    PP_URL,                             PP_RSS,         PP_BIAS,        pp_fetch),
    (SW_SLUG,        SW_NAME,                    SW_URL,                             SW_RSS,         SW_BIAS,        sw_fetch),
]


def _ensure_source(engine, slug, name, url, rss_url=None, bias_lean=None) -> int:
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO wtf.sources (slug, name, url, rss_feed, bias_lean)
                VALUES (:s, :n, :u, :r, :b)
                ON CONFLICT (slug) DO UPDATE SET
                    name=EXCLUDED.name,
                    url=EXCLUDED.url,
                    rss_feed=COALESCE(EXCLUDED.rss_feed, wtf.sources.rss_feed),
                    bias_lean=COALESCE(EXCLUDED.bias_lean, wtf.sources.bias_lean)
            """),
            {"s": slug, "n": name, "u": url, "r": rss_url, "b": bias_lean},
        )
        return c.execute(text("SELECT id FROM wtf.sources WHERE slug=:s"), {"s": slug}).scalar()


def _process_source(engine, slug, name, url, rss_url, bias_lean, fetch_fn, stats):
    """Fetch + normalize + score + persist one source. Mutates stats in place."""
    sid = _ensure_source(engine, slug, name, url, rss_url, bias_lean)
    try:
        raw_articles = fetch_fn()
    except Exception as exc:
        log.exception("%s fetch failed", slug)
        record_failure(engine, slug, {}, f"fetch: {exc}")
        stats["failed"] += 1
        return
    for raw in raw_articles:
        try:
            article = canonicalize(raw)
            bias = score_bias(article["title"], article["body"])
            aid = upsert_article(engine, sid, article, bias, source_slug=slug)
            if aid:
                stats["inserted"] += 1
                stats["inserted_ids"].append(aid)
                creed_emit("wtf.article.ingested", {
                    "source": slug, "url": article["url"], "bias": bias["band"],
                })
            else:
                stats["skipped"] += 1
        except Exception as exc:
            log.exception("article failed: %s", raw.get("url"))
            record_failure(engine, slug, raw, str(exc))
            stats["failed"] += 1


def run_once(engine) -> dict:
    """Run one ingestion pass across all registered sources. Returns stats dict."""
    stats = {"inserted": 0, "skipped": 0, "failed": 0, "inserted_ids": []}
    for slug, name, url, rss_url, bias_lean, fetch_fn in SOURCES:
        _process_source(engine, slug, name, url, rss_url, bias_lean, fetch_fn, stats)

    # DB-driven generic sources — any wtf.sources row with rss_feed set that is
    # not already handled by a dedicated entry in SOURCES above. New sources added
    # to the DB via migrations are automatically ingested with zero code change.
    handled_slugs = frozenset(s for s, *_ in SOURCES)
    from ingest.sources.rss_generic import fetch_rss as _generic_fetch
    from ingest.sources.sitemap_generic import fetch_sitemap as _sitemap_fetch
    try:
        with engine.connect() as c:
            db_rows = c.execute(
                text("SELECT slug, name, url, rss_feed, bias_lean FROM wtf.sources WHERE rss_feed IS NOT NULL")
            ).mappings().all()
        for src in db_rows:
            if src["slug"] in handled_slugs:
                continue
            _slug = src["slug"]
            _rss = src["rss_feed"]
            if _rss.startswith("sitemap:"):
                # RSS-less source (#4909, e.g. Postmedia) — sitemap-index path.
                # Pass recently-known URLs so title lookups only hit NEW pages.
                _map_url = _rss[len("sitemap:"):]
                try:
                    with engine.connect() as c:
                        _known = {r[0] for r in c.execute(
                            text("""
                                SELECT a.url FROM wtf.articles a
                                JOIN wtf.sources s ON s.id = a.source_id
                                WHERE s.slug = :s
                                  AND a.ingested_at > NOW() - INTERVAL '14 days'
                            """), {"s": _slug}).fetchall()}
                except Exception:
                    _known = set()
                fetch_fn = lambda u=_map_url, s=_slug, k=_known: _sitemap_fetch(u, s, known_urls=k)
            else:
                fetch_fn = lambda u=_rss, s=_slug: _generic_fetch(u, s)
            _process_source(engine, _slug, src["name"] or _slug,
                            src["url"] or "", _rss,
                            src["bias_lean"] or "center", fetch_fn, stats)
    except Exception as exc:
        log.warning("db-driven generic sources failed: %s", exc)

    log.info("run_once: %s", {k: v for k, v in stats.items() if k != "inserted_ids"})

    # Recompute rolling outlet bias scores after each pass
    try:
        from ingest.outlet_bias import recompute_outlet_bias
        recompute_outlet_bias(engine)
    except Exception as exc:
        log.warning("outlet_bias recompute failed: %s", exc)

    # Recompute cluster-level metrics: coverage gap score + certainty label
    try:
        from ingest.cluster_metrics import compute_cluster_metrics
        compute_cluster_metrics(engine)
    except Exception as exc:
        log.warning("cluster_metrics recompute failed: %s", exc)

    # F.A.C.T. orchestrator: AI deep-analysis for priority articles
    try:
        from sqlalchemy import text as _text
        priority_ids = pick_priority_articles(engine, "wtf", stats.get("inserted_ids", []))
        for article_id in priority_ids:
            with engine.connect() as c:
                row = c.execute(
                    _text("""
                        SELECT a.title, a.body, s.slug AS source_slug
                        FROM wtf.articles a
                        JOIN wtf.sources s ON s.id = a.source_id
                        WHERE a.id = :id
                    """),
                    {"id": article_id},
                ).fetchone()
            if not row:
                continue
            bias_result = ai_analyze("bias", article_id, row.title or "", row.body or "")
            if bias_result:
                with engine.begin() as c:
                    c.execute(
                        _text("""
                            UPDATE wtf.bias_scores SET
                                analyzed_by = 'BIAS_LLM',
                                trigger_phrases = :tp,
                                confidence = :conf
                            WHERE article_id = :aid
                        """),
                        {
                            "tp": json.dumps(bias_result.get("trigger_phrases", [])),
                            "conf": bias_result.get("confidence"),
                            "aid": article_id,
                        },
                    )
            verify_result = ai_analyze("factcheck", article_id, row.title or "", row.body or "")
            if verify_result:
                with engine.begin() as c:
                    c.execute(
                        _text("""
                            UPDATE wtf.fact_checks SET
                                analyzed_by = 'VERIFY_LLM',
                                claims = :claims,
                                overall_verdict = :verdict
                            WHERE article_id = :aid
                        """),
                        {
                            "claims": json.dumps(verify_result.get("claims", [])),
                            "verdict": verify_result.get("overall_verdict"),
                            "aid": article_id,
                        },
                    )
            # Beat classification — fast path for priority articles.
            # Backlog worker (WTF_BEAT_BACKLOG_ENABLED) handles historical articles.
            beat_result = ai_analyze("classify_beat", article_id, row.title or "", row.body or "")
            if beat_result:
                _beat = (beat_result.get("beat") or "").strip().lower()
                _beat_val = _beat if _beat in beat_backlog_worker.VALID_BEATS else "none"
                with engine.begin() as c:
                    c.execute(
                        _text(
                            "UPDATE wtf.articles SET beat = :beat WHERE id = :id AND beat IS NULL"
                        ),
                        {"beat": _beat_val, "id": article_id},
                    )
            # Geo extraction — fast path for priority articles.
            # Backlog worker (WTF_GEO_BACKLOG_ENABLED) handles historical articles.
            from ingest.geocoder import extract_geo as _extract_geo
            geo_result = _extract_geo(
                article_id,
                row.title or "",
                row.body or "",
                getattr(row, "source_slug", None) or "",
            )
            if geo_result:
                with engine.begin() as c:
                    c.execute(
                        _text("""
                            UPDATE wtf.articles
                            SET province_code = :pc,
                                city          = :city,
                                lat           = :lat,
                                lng           = :lng,
                                country_code  = :country,
                                geo_scope     = :geo_scope,
                                analysis_tier = CASE
                                    WHEN analysis_tier = 'pending' THEN 'quick_v1'
                                    ELSE analysis_tier
                                END,
                                tier1_at = COALESCE(tier1_at, NOW())
                            WHERE id = :id AND geo_scope IN ('national')
                        """),
                        {
                            "id": article_id,
                            "pc": geo_result.get("province_code"),
                            "city": geo_result.get("city"),
                            "lat": geo_result.get("lat"),
                            "lng": geo_result.get("lng"),
                            "country": geo_result.get("country_code"),
                            "geo_scope": geo_result.get("geo_scope") or "unmappable",
                        },
                    )
            mark_ai_analyzed(engine, article_id, "wtf")
        log.info("orchestrator: %d articles AI-analyzed this cycle", len(priority_ids))
    except Exception as exc:
        log.warning("orchestrator: failed: %s", exc)

    return stats


def run_geo_report(engine) -> None:
    """Weekly geo report: province × outlet coverage matrix + news deserts → wtf.geo_reports."""
    today = datetime.date.today()
    try:
        with engine.connect() as c:
            rows = c.execute(
                text("""
                    SELECT a.province_code, s.slug AS outlet, COUNT(*) AS cnt
                    FROM wtf.articles a
                    JOIN wtf.sources s ON s.id = a.source_id
                    WHERE a.published_at >= NOW() - INTERVAL '7 days'
                      AND a.province_code IS NOT NULL
                    GROUP BY a.province_code, s.slug
                    ORDER BY a.province_code, cnt DESC
                """)
            ).fetchall()
    except Exception as exc:
        log.warning("geo_report: DB query failed: %s", exc)
        return

    matrix: dict = {}
    for row in rows:
        pc = row.province_code
        if pc not in matrix:
            matrix[pc] = {}
        matrix[pc][row.outlet] = int(row.cnt)

    province_coverage = {pc: sum(outlets.values()) for pc, outlets in matrix.items()}
    all_provinces = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
    news_deserts = [pc for pc in all_provinces if province_coverage.get(pc, 0) < 5]

    try:
        with engine.begin() as c:
            c.execute(
                text("""
                    INSERT INTO wtf.geo_reports (report_date, province_coverage, outlet_province_matrix, news_deserts)
                    VALUES (:d, :pc, :matrix, :nd)
                    ON CONFLICT (report_date) DO UPDATE SET
                        province_coverage = EXCLUDED.province_coverage,
                        outlet_province_matrix = EXCLUDED.outlet_province_matrix,
                        news_deserts = EXCLUDED.news_deserts
                """),
                {
                    "d": today,
                    "pc": json.dumps(province_coverage),
                    "matrix": json.dumps(matrix),
                    "nd": json.dumps(news_deserts),
                },
            )
    except Exception as exc:
        log.warning("geo_report: write failed: %s", exc)
        return

    log.info(
        "geo_report: %d provinces covered, %d news deserts: %s",
        len(province_coverage),
        len(news_deserts),
        news_deserts,
    )


def main():
    engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    _last_report_date = None
    _last_parliament_date = None
    _last_aurora_date = None
    _last_city_hour = None
    _last_covered_date = None   # entity-graph WTF covered_by reconcile (daily)
    _last_ec_date = None        # entity-graph EC donations reconcile (weekly, Sat)
    _last_dedup_date = None     # entity-graph dedup engine (weekly, Mon)
    _last_securities_date = None  # TSX issuer directory ingest (weekly, Tue) — #373 Market L6 Phase 0
    _last_securities_eg_date = None  # securities -> graph reconcile (market_reaction_to, weekly Wed) — L6 step 2
    _last_drift_date = None     # parliamentary cost/funds drift guard (daily)
    _last_dept_contracts_date = None  # dept contract-award rollup mirror (#373 Contract link, daily)
    _last_issuer_contracts_date = None  # issuer contract rollup mirror (#373 Contract->Market L6, daily)
    while True:
        # Weekly geo report on Mondays
        today = datetime.date.today()
        if today.weekday() == 0 and _last_report_date != today:
            run_geo_report(engine)
            _last_report_date = today

        # Weekly parliamentary sync on Sundays (MPs, votes, ballots, article tagging)
        if today.weekday() == 6 and _last_parliament_date != today:
            try:
                from ingest.parliament.openparl import run_parliament_sync
                result = run_parliament_sync(engine)
                log.info("parliament sync: %s", result)
            except Exception:
                log.exception("parliament sync crashed — skipping this week")

            # Cabinet-role refresh from pm.gc.ca (runs AFTER MPs are synced so it
            # matches against the fresh roster).  Own try/except + ingest_log row
            # so a failure never kills the senators sync or the entity-graph step.
            try:
                from ingest.parliament.cabinet import refresh_cabinet
                cab = refresh_cabinet(engine)
                log.info("cabinet refresh: %s", cab)
                with engine.begin() as _c:
                    _c.execute(text(
                        "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                        "VALUES ('cabinet_refresh', :f, :u)"),
                        {"f": cab.get("fetched", 0),
                         "u": cab.get("added", 0) + cab.get("changed", 0) + cab.get("removed", 0)})
            except Exception as exc:
                log.exception("cabinet refresh crashed")
                try:
                    with engine.begin() as _c:
                        _c.execute(text(
                            "INSERT INTO parliament.ingest_log (task, error) "
                            "VALUES ('cabinet_refresh', :e)"), {"e": str(exc)[:500]})
                except Exception:
                    pass

            # Senate roster + enrichment sync (previously NOT wired into the weekly
            # run).  Own try/except + ingest_log row.
            try:
                from ingest.parliament.senators import sync_senators
                sen = sync_senators()
                log.info("senators sync: %s", sen)
                with engine.begin() as _c:
                    _c.execute(text(
                        "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                        "VALUES ('senators_sync', :f, :u)"),
                        {"f": sen.get("total", 0),
                         "u": sen.get("updated", 0) + sen.get("departed", 0) + sen.get("appointed", 0)})
            except Exception as exc:
                log.exception("senators sync crashed")
                try:
                    with engine.begin() as _c:
                        _c.execute(text(
                            "INSERT INTO parliament.ingest_log (task, error) "
                            "VALUES ('senators_sync', :e)"), {"e": str(exc)[:500]})
                except Exception:
                    pass

            # Senate senators' quarterly expenditures (sencanada.ca proactive
            # disclosure).  Runs AFTER the roster sync so rows match the fresh
            # senators.  Own try/except + ingest_log row.
            try:
                # run_senator_expenses_sync SELF-LOGS to parliament.ingest_log now
                # (task='senator_expenses_sync'), like the other syncs — no inline INSERT needed.
                from ingest.parliament.senator_expenses import run_senator_expenses_sync
                log.info("senator_expenses sync: %s", run_senator_expenses_sync(engine))
            except Exception:
                log.exception("senator_expenses sync crashed")

            # Entity graph: refresh cast_vote edges (Link 3) now that new votes synced (#373)
            try:
                from ingest.entity_graph_parliament_reconcile import run as _parl_eg
                log.info("entity_graph parliament reconcile: %s", _parl_eg())
            except Exception:
                log.exception("entity_graph parliament reconcile crashed")
            _last_parliament_date = today
        try:
            run_once(engine)
        except Exception:
            log.exception("run_once crashed — sleeping and retrying")

        # Tag new articles with MP mentions after every ingest cycle.
        # Full parliament sync (MPs + votes) stays weekly on Sundays.
        try:
            from ingest.parliament.openparl import tag_articles
            result = tag_articles(engine, days_back=1)
            if result.get("tagged"):
                log.info("mp_tagging: %s", result)
        except Exception:
            log.exception("mp_tagging crashed — skipping this cycle")

        # Sync article_mp_tags → shared.entity_mentions (Task #3024 entity graph).
        # Also seeds party org entities and MP→Party edges (idempotent no-ops after first run).
        try:
            from ingest.shared.entity_mentions_sync import run_entity_mentions_sync
            em = run_entity_mentions_sync(engine, days_back=2)
            if em["article_mentions"]["synced"]:
                log.info("entity_mentions: %s", em["article_mentions"])
        except Exception:
            log.exception("entity_mentions_sync crashed — skipping this cycle")

        # Entity-graph reconciles (project #373) — keep the Shared Entity Graph fresh.
        # All idempotent + set-based (the hub DB does the work). cast_vote (Link 3) runs in
        # the Sunday parliament block above. Here: covered_by (Link 7) daily; EC donations
        # (Link 1) weekly on Saturdays (heavy 4.8M-row aggregate). Failures only log.
        if _last_covered_date != today:
            try:
                from ingest.entity_graph_wtf_reconcile import run as _wtf_eg
                log.info("entity_graph wtf reconcile: %s", _wtf_eg())
            except Exception:
                log.exception("entity_graph wtf reconcile crashed")
            _last_covered_date = today

        # Department contract-award rollup (#373 "Contract" chain link) — daily. Mirrors Gov
        # Watch's canonical-department contract totals into parliament.dept_contracts so the cost
        # pages can sit a minister's office cost beside the federal contract volume their portfolio
        # oversees. Fail-loud (parliament.ingest_log); the drift guard below watches it. Runs
        # BEFORE the guard so a same-day refresh is already fresh when the guard checks freshness.
        if _last_dept_contracts_date != today:
            try:
                from ingest.parliament.dept_contracts import run_dept_contracts_sync
                log.info("parliament dept_contracts sync: %s", run_dept_contracts_sync(engine))
            except Exception:
                log.exception("parliament dept_contracts sync crashed")
            _last_dept_contracts_date = today

        # Issuer contract-award rollup (#373 "Contract -> Market" link, L6) — daily. Mirrors Gov
        # Watch's per-TSX-issuer contract totals into securities.issuer_contracts, adding the
        # dollar footprint to the already-live market_reaction_to graph edge ("company X won $Y
        # federal, its stock is TSX:X"). Fail-loud (parliament.ingest_log task='issuer_contracts').
        if _last_issuer_contracts_date != today:
            try:
                from ingest.securities_issuer_contracts import run_issuer_contracts_sync
                log.info("securities issuer_contracts sync: %s", run_issuer_contracts_sync(engine))
            except Exception:
                log.exception("securities issuer_contracts sync crashed")
            _last_issuer_contracts_date = today

        # A.U.R.O.R.A. environmental layers — daily (project #393).
        # CWFIS only: allow-all robots.txt, verified. NOT api.weather.gc.ca,
        # which disallows /collections/*/items (ADR-001, owner decision).
        # Runs BEFORE the drift guard so the guard evaluates a heartbeat written
        # this pass, not yesterday's. run_aurora_cwfis never raises and writes
        # its own heartbeats on both the success and swallowed-error paths.
        if _last_aurora_date != today:
            try:
                from ingest.weather.cwfis import run_aurora_cwfis
                log.info("aurora cwfis: %s", run_aurora_cwfis(engine))
            except Exception:
                log.exception("aurora cwfis crashed")
            _last_aurora_date = today

        # A.U.R.O.R.A. city observations + forecasts — HOURLY, not daily.
        # citypage_weather is a current-conditions feed: its layer goes stale
        # after 3h, so a daily gate would leave the cards wrong for most of the
        # day. Gated on the UTC HOUR so a 30-min loop still fires it once per
        # hour rather than twice. Same contract as cwfis: never raises, writes
        # its own heartbeats on every path, and runs BEFORE the drift guard so
        # the guard reads a heartbeat from this pass.
        # UTC, not local: the feed partitions by UTC hour, so a local-time key
        # would fire twice (or skip) around a DST boundary.
        _city_hour = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H")
        if _last_city_hour != _city_hour:
            try:
                from ingest.weather.citypage import run_aurora_citypage
                log.info("aurora citypage: %s", run_aurora_citypage(engine))
            except Exception:
                log.exception("aurora citypage crashed")
            _last_city_hour = _city_hour

        # Parliamentary cost/funds DRIFT GUARD — daily. Self-policing: reconciliation still ties
        # out + every ingest source is fresh & not erroring. Alerts Kytran through A.R.C.H.I.E.
        # on onset; logs to parliament.ingest_log either way (it can't silently stop the way the
        # sources it watches once did — mp_expenses 8wk / ec_contributions 3wk).
        if _last_drift_date != today:
            try:
                from ingest.parliament.drift_guard import run_drift_guard
                log.info("parliament drift guard: %s", run_drift_guard(engine))
            except Exception:
                log.exception("parliament drift guard crashed")
            _last_drift_date = today

        if today.weekday() == 5 and _last_ec_date != today:
            try:
                from ingest.entity_graph_ec_donations_reconcile import run as _ec_eg
                log.info("entity_graph EC donations reconcile: %s", _ec_eg())
            except Exception:
                log.exception("entity_graph EC donations reconcile crashed")
            _last_ec_date = today

        # Dedup engine weekly on Mondays — after the weekend feeders (Sat EC, Sun parliament)
        # add entities. Exact normalized-name: orgs auto-merge (revertable, distinct-guarded),
        # persons -> merge_review_queue. Idempotent. THEN fuzzy/trigram ORG candidates ->
        # merge_review_queue for human review (#4207) — non-destructive (review-only, never
        # auto-merged, deduped vs queue+decisions). The review UI it was gated on now exists
        # (consumer/dedup_review.html). Runs HERE (ingest loop, no web timeout — the trigram
        # scan is ~3 min over ~42k orgs). Gated by WTF_DEDUP_FUZZY_SCHEDULED (default on).
        if today.weekday() == 0 and _last_dedup_date != today:
            try:
                from ingest.entity_graph_dedup import run as _dedup
                log.info("entity_graph dedup: %s", _dedup())
                if os.environ.get("WTF_DEDUP_FUZZY_SCHEDULED", "1").lower() not in ("0", "false", "no"):
                    from ingest.entity_graph_dedup import fuzzy_candidates as _fuzzy
                    log.info("entity_graph dedup fuzzy: %s", _fuzzy())
            except Exception:
                log.exception("entity_graph dedup crashed")
            _last_dedup_date = today

        # TSX listed-issuer directory refresh weekly on Tuesdays (#373 Market L6 Phase 0).
        # Builds securities.issuers (name<->ticker bridge). Lightweight Wikipedia fetch +
        # upsert; a thin/failed fetch self-skips. NOTE: chain Link 6 (market_reaction_to)
        # stays has_data=false — it needs CORPORATE contract-award data in awarded_to first;
        # the current awarded_to vendors are individuals (TBS proactive disclosure), 0 issuer
        # overlap. This keeps the issuer bridge fresh so L6 can light up once that data lands.
        if today.weekday() == 1 and _last_securities_date != today:
            try:
                from ingest.securities_issuer_ingest import run as _sec_ingest
                log.info("securities issuer ingest: %s", _sec_ingest())
            except Exception:
                log.exception("securities issuer ingest crashed")
            _last_securities_date = today

        # Market chain Link 6 (market_reaction_to) weekly on Wednesdays (#373 step 2) —
        # after Tue issuer ingest + the daily gov awards. Matches corporate contract vendors
        # to TSX securities (exact-norm) -> market_reaction_to edges, flips has_data. Idempotent.
        if today.weekday() == 2 and _last_securities_eg_date != today:
            try:
                from ingest.entity_graph_securities_reconcile import run as _sec_eg
                log.info("entity_graph securities reconcile: %s", _sec_eg())
            except Exception:
                log.exception("entity_graph securities reconcile crashed")
            _last_securities_eg_date = today

        # Backlog workers — all run in PARALLEL. Each is fully independent:
        # different DB tables, different agents, different fleet nodes.
        # One slow worker (geo, llm) no longer starves the others.
        _backlog_workers = (
            cluster_backlog_worker,
            scout_body_backlog_worker,
            geo_backlog_worker,
            factcheck_backlog_worker,
            llm_analysis_backlog_worker,
            bias_v2_backlog_worker,
            beat_backlog_worker,       # WTF_BEAT_BACKLOG_ENABLED=true to activate
        )
        with ThreadPoolExecutor(max_workers=len(_backlog_workers)) as pool:
            future_to_worker = {
                pool.submit(w.run_backlog, engine): w
                for w in _backlog_workers
            }
            for fut in as_completed(future_to_worker):
                w = future_to_worker[fut]
                try:
                    result = fut.result()
                    if result.get("stopped") != "disabled":
                        log.info("backlog %s: %s", w.__name__, result)
                except Exception:
                    log.exception("%s crashed", w.__name__)

        # Alerts digest — separate API (run_digest, not run_backlog)
        try:
            result = alerts_digest_worker.run_digest(engine)
            if result.get("matched") or result.get("errors"):
                log.info("alerts_digest: %s", result)
        except Exception:
            log.exception("alerts_digest crashed")

        # Google Fact Check Tools API partner signal (#2137)
        try:
            result = factcheck_partner_worker.run_partner_check(engine)
            if result.get("stopped") != "disabled":
                log.info("factcheck_partner: %s", result)
        except Exception:
            log.exception("factcheck_partner crashed")

        # Weekly bias digest — Monday only, default OFF
        try:
            result = weekly_digest_worker.run_weekly_digest(engine)
            if result.get("sent") or result.get("errors"):
                log.info("weekly_digest: %s", result)
        except Exception:
            log.exception("weekly_digest crashed")

        # KBS CRM sync — push new newsletter subscribers to kbs_crm (#4899).
        # Default OFF until KBS_INTERNAL_KEY is set; unreachable KBS defers
        # the batch to the next cycle (kbs_synced_at stays NULL).
        try:
            result = newsletter_kbs_sync.run_sync(engine)
            if result.get("synced") or result.get("errors"):
                log.info("newsletter_kbs_sync: %s", result)
        except Exception:
            log.exception("newsletter_kbs_sync crashed")

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
