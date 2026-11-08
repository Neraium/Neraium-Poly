"""Engineering cache tests, no genuine market/profit data."""
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase31.operations import EventSummaryCache


def test_verification_is_background_only_and_snapshot_does_not_repeat_source_reads():
    calls=[];cache=EventSummaryCache()
    def produce():calls.append(1);return {'status':'research_only','domains':{'weather':{'forecasts':4}},'historical_qualification':{'events':250,'private_full_history':['large evidence'],'qualified_training_events':0}}
    assert cache.snapshot()['summary_status']=='withheld'
    cache.refresh(produce)
    for _ in range(10):
        r=cache.snapshot();r['domains']['weather']['forecasts']=999
    r=cache.snapshot();assert calls==[1] and r['domains']['weather']['forecasts']==4
    assert 'private_full_history' not in r['historical_qualification']
    assert r['summary_status']=='cached_verified_snapshot' and not r['trading_authority']


def test_expired_or_failed_verification_never_presents_stale_counters_as_current():
    now=[0.];cache=EventSummaryCache(monotonic=lambda:now[0])
    cache.refresh(lambda:{'counts':{'verified':8}});now[0]=121
    r=cache.snapshot();assert r['status']=='stale' and 'counts' not in r
    cache.failed(ValueError('CONTROLLED'))
    assert cache.snapshot()['summary_refresh_error']=='ValueError'
    now[0]=-1;assert cache.snapshot()['summary_status']=='withheld'


def test_verification_timestamp_remains_separate_from_request_time():
    now=[datetime(2026,11,8,tzinfo=UTC)];ticks=[0.]
    cache=EventSummaryCache(clock=lambda:now[0],monotonic=lambda:ticks[0])
    cache.refresh(lambda:{'forecasts':4});now[0]+=timedelta(seconds=10);ticks[0]+=10
    r=cache.snapshot();assert r['summary_age_seconds']==10 and r['summary_verified_completed_at']=='2026-11-08T00:00:00+00:00'


def test_large_unbounded_history_fails_closed_without_replacing_last_good_verification():
    cache=EventSummaryCache();cache.refresh(lambda:{'forecasts':1})
    with pytest.raises(ValueError):cache.refresh(lambda:{'raw':'x'*(300*1024)})
    assert cache.snapshot()['forecasts']==1


def test_fresh_cache_with_verification_failure_immediately_withholds_old_values():
    cache=EventSummaryCache();cache.refresh(lambda:{'counts':{'verified':8}})
    cache.failed(ValueError('CONTROLLED integrity failure'))
    assert cache.snapshot()['summary_status']=='withheld' and 'counts' not in cache.snapshot()
    cache.refresh(lambda:{'counts':{'verified':8}})
    assert cache.snapshot()['summary_status']=='cached_verified_snapshot'


def test_operations_preserves_verified_snapshot_age_and_never_freshens_it():
    from types import SimpleNamespace

    from neraium_poly.research.phase15.operations import experimental_research
    cache=EventSummaryCache();cache.refresh(lambda:{"domains":{"forecasts":1}})
    runtime=SimpleNamespace(account=SimpleNamespace(risk=SimpleNamespace(snapshot=lambda **k:{"kill_switch":True})),
        clock=lambda:datetime.now(UTC),event_operations_summary=cache.snapshot,
        phase18=None,phase18_error=None,phase17=None,phase17_error=None,phase16=None,phase16_error=None,
        phase15_relationships=None,phase16_execution_status=lambda **k:{})
    r=experimental_research(runtime,for_operations=True)
    assert r["event_summary_verification"]["summary_status"]=="cached_verified_snapshot"
    assert r["event_summary_verification"]["summary_age_seconds"]>=0
    assert r["event_summary_verification"]["summary_verified_completed_at"]
