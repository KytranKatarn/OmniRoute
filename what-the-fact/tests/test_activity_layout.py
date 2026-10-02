"""/activity two-column layout (design wtf-activity). Renders the real template with a
permissive fake context (no DB). Run without pytest: python3 tests/test_activity_layout.py"""
from __future__ import annotations

import pathlib
import re

TPL = str(pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates")
from jinja2 import Environment,DictLoader,FileSystemLoader,ChoiceLoader,ChainableUndefined
def R(**k): return D5(k)
class D5(dict):
    def __getattr__(s,k): return s.get(k,5)
    def __missing__(s,k): return 5
def render(path_dir=TPL, subscriber=True):
    env=Environment(autoescape=True,undefined=ChainableUndefined,loader=ChoiceLoader([
        DictLoader({'base.html':'{% block title %}{% endblock %}{% block content %}{% endblock %}'}),FileSystemLoader(path_dir)]))
    env.filters.setdefault('urlencode',lambda x:str(x))
    ctx=dict(is_subscriber=subscriber,stats=D5(),trends=D5(),stats_as_of='now',
      creed_scan=dict(grade='B',overall=90,event_count=5,by_category={'safety':dict(score=90,provisional=False)}),
      agent_throughput=[],source_health=[R(name='CBC',articles_7d=4,body_pct=80,owner_type='public',lean='left',articles_30d=9,ownership='public')],
      top_stories=[R(id=1,title='Top story',cnt=3,outlets=2,published_at=None)],
      beat_breakdown=[R(beat='politics',cnt=7,pct=50,name='politics')],bias_spectrum=[R(label='left',cnt=3,bucket='left',pct=40,band='left',count=3,name='x')],
      throughput_sparkline=[R(n=1),R(n=2),R(n=3)],
      llm_rate=5,llm_hours_left=2,llm_pending_count=9,astats=None,spark=None,
      events=[R(ts='2026-10-01T10:00:00',performed_by='X',article_id=1,title='Ev',stage='bias',result='ok',created_at=None,source='CBC',ago='1m',agent='B.I.A.S.',when='now',success=True)],
      total=1,page=1,total_pages=1,agent_filter='all',nr=dict(agents=[R(name='A',fact_checks=1,bias_scores=2,agent='A',total=3)],unattributed=1),
      newsroom=dict(agents=[],unattributed=0))
    from jinja2.exceptions import UndefinedError
    for _ in range(40):
        try: return env.get_template('activity.html').render(**ctx)
        except UndefinedError as e:
            m=re.match(r"'(\w+)' is undefined",str(e))
            if not m: raise
            ctx[m.group(1)]={}
    raise RuntimeError('too many undefined')


def _strip(h):
    return re.sub(r"<style>.*?</style>|<script>.*?</script>", "", h, flags=re.S)


def test_subscriber_gets_main_and_aside_columns_and_balanced_divs():
    h = _strip(render())
    assert 'class="wtf-act-cols"' in h and 'class="wtf-act-main"' in h and "<aside" in h
    assert len(re.findall(r"<div\b", h)) == len(re.findall(r"</div>", h))


def test_aside_holds_the_compact_panels_and_main_holds_the_wide_ones():
    h = _strip(render())
    main, aside = h.split("<aside")
    aside = aside.split("</aside>")[0]
    for t in ("Top stories today", "Beat breakdown", "Source bias spectrum", "Story cluster sizes",
              "Pipeline Health", "who did the work"):
        assert t in aside, t
    for t in ("Source health", "Tier distribution"):
        assert t in main, t


def test_event_log_stays_full_width_below_the_columns():
    h = _strip(render())
    assert h.index("</aside>") < h.index('class="wtf-act-wrap--btm"') < h.index('id="wtf-act-table"')


def test_governance_banner_renders_once():
    assert _strip(render()).count("AI Newsroom Governance") == 1


def test_non_subscriber_sees_paywall_not_the_columns():
    h = _strip(render(subscriber=False))
    assert "wtf-act-cols" not in h and "Starter+" in h


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
