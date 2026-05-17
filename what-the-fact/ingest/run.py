"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import datetime
import json
import logging
import os
import time
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
from ingest.sources.montreal_gazette import fetch_articles as mg_fetch, SOURCE_SLUG as MG_SLUG, SOURCE_NAME as MG_NAME, SOURCE_URL as MG_URL, RSS_URL as MG_RSS, BIAS_LEAN as MG_BIAS
from ingest.sources.ottawa_citizen import fetch_articles as oc_fetch, SOURCE_SLUG as OC_SLUG, SOURCE_NAME as OC_NAME, SOURCE_URL as OC_URL, RSS_URL as OC_RSS, BIAS_LEAN as OC_BIAS
from ingest.sources.calgary_herald import fetch_articles as ch_fetch, SOURCE_SLUG as CH_SLUG, SOURCE_NAME as CH_NAME, SOURCE_URL as CH_URL, RSS_URL as CH_RSS, BIAS_LEAN as CH_BIAS
from ingest.sources.edmonton_journal import fetch_articles as ej_fetch, SOURCE_SLUG as EJ_SLUG, SOURCE_NAME as EJ_NAME, SOURCE_URL as EJ_URL, RSS_URL as EJ_RSS, BIAS_LEAN as EJ_BIAS
from ingest.sources.saskatoon_starphoenix import fetch_articles as sp_fetch, SOURCE_SLUG as SP_SLUG, SOURCE_NAME as SP_NAME, SOURCE_URL as SP_URL, RSS_URL as SP_RSS, BIAS_LEAN as SP_BIAS
from ingest.sources.regina_leaderpost import fetch_articles as rl_fetch, SOURCE_SLUG as RL_SLUG, SOURCE_NAME as RL_NAME, SOURCE_URL as RL_URL, RSS_URL as RL_RSS, BIAS_LEAN as RL_BIAS
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
    (MG_SLUG,        MG_NAME,                    MG_URL,                             MG_RSS,         MG_BIAS,        mg_fetch),
    (OC_SLUG,        OC_NAME,                    OC_URL,                             OC_RSS,         OC_BIAS,        oc_fetch),
    # ── Expansion batch 2: regional, French-language, Indigenous, business ─────
    (CH_SLUG,        CH_NAME,                    CH_URL,                             CH_RSS,         CH_BIAS,        ch_fetch),
    (EJ_SLUG,        EJ_NAME,                    EJ_URL,                             EJ_RSS,         EJ_BIAS,        ej_fetch),
    (SP_SLUG,        SP_NAME,                    SP_URL,                             SP_RSS,         SP_BIAS,        sp_fetch),
    (RL_SLUG,        RL_NAME,                    RL_URL,                             RL_RSS,         RL_BIAS,        rl_fetch),
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
    log.info("run_once: %s", {k: v for k, v in stats.items() if k != "inserted_ids"})

    # Recompute rolling outlet bias scores after each pass
    try:
        from ingest.outlet_bias import recompute_outlet_bias
        recompute_outlet_bias(engine)
    except Exception as exc:
        log.warning("outlet_bias recompute failed: %s", exc)

    # F.A.C.T. orchestrator: AI deep-analysis for priority articles
    try:
        from sqlalchemy import text as _text
        priority_ids = pick_priority_articles(engine, "wtf", stats.get("inserted_ids", []))
        for article_id in priority_ids:
            with engine.connect() as c:
                row = c.execute(
                    _text("SELECT title, body FROM wtf.articles WHERE id = :id"),
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
    while True:
        # Weekly geo report on Mondays
        today = datetime.date.today()
        if today.weekday() == 0 and _last_report_date != today:
            run_geo_report(engine)
            _last_report_date = today
        try:
            run_once(engine)
        except Exception:
            log.exception("run_once crashed — sleeping and retrying")

        # Backlog workers — cheapest first, all default OFF via *_ENABLED env flags.
        # Each is independent; one failure must not block the others.
        for worker in (
            cluster_backlog_worker,
            geo_backlog_worker,
            factcheck_backlog_worker,
            llm_analysis_backlog_worker,
        ):
            try:
                result = worker.run_backlog(engine)
                if result.get("stopped") != "disabled":
                    log.info("backlog %s: %s", worker.__name__, result)
            except Exception:
                log.exception("%s crashed", worker.__name__)

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
