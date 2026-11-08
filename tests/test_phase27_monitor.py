"""Controlled mobile monitor fixtures, not live trading results."""
from datetime import UTC, datetime

from neraium_poly.ops.monitor import render_monitor


def test_findings_view_fits_phone_and_keeps_unknown_edge_unreported():
    now=datetime.now(UTC).isoformat()
    e={'generated_at':now,'cash':496.11522,'operations_research':{'phase27':{
        'status':'research_only','as_of':now,'counts':{'findings_evaluated':60,'qualified_research_findings':0,'reviewed_canonical_groups':27},
        'rejections':{'uncalibrated_forecast':60},'latest_findings':[{'market_id':'CONTROLLED','forecast_probability':.5,'executable_ask':.55,'estimated_after_cost_edge':None,'confidence_status':'unvalidated'}]}}}
    for width in [32,42,80]:
        text=render_monitor({'cash':500},e,width=width,height=20,view='findings').plain
        assert all(len(line)<=width for line in text.splitlines())
        assert 'Qualified 0' in text and 'insufficient evidence' in text
        assert 'NO TRADE' in text


def test_stale_findings_do_not_display_old_qualification_as_current():
    e={'generated_at':datetime.now(UTC).isoformat(),'operations_research':{'phase27':{'status':'research_only','as_of':'2020-01-01T00:00:00+00:00','counts':{'qualified_research_findings':999}}}}
    text=render_monitor({},e,view='findings').plain
    assert 'stale' in text and '999' not in text
