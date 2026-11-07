"""Controlled operational samples; cached storage is never fresh admission evidence."""
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from neraium_poly.ops.monitor import render_monitor
from neraium_poly.research.phase15.budgets import capacity_status
from rich.console import Console
from test_phase15_monitor import sample


def archive(now, *, age=10, status='cached'):
    return {'snapshot_only': True, 'admission_authority': False, 'measurement_status': status,
        'measurement_at': (now-timedelta(seconds=age)).isoformat(), 'measurement_age_seconds': age,
        'free_space_measured_at': now.isoformat(), 'health': 'ok',
        'usage_bytes': 3*1024**3, 'budget_bytes': 64*1024**3,
        'free_bytes': 400*1024**3, 'global_floor_bytes': 100*1024**3,
        'growth_bytes_per_second': 1000, 'tier_usage_bytes': {}}


@pytest.mark.parametrize('age,status', [(120, 'cached'), (10, 'stale'), (-1, 'cached')])
def test_fresh_http_response_cannot_freshen_old_or_invalid_archive_sample(age, status):
    now = datetime.now(UTC)
    a = archive(now, age=age, status=status)
    a['measurement_age_seconds'] = 0  # API age claims cannot override the actual measurement clock.
    r = capacity_status(a, service='collector', now=now, generated_at=now.isoformat())
    assert r['status'] == 'blocked' and r['backpressure']
    assert 'stale_capacity_observation' in r['alerts']
    assert r['seconds_to_capacity'] is None and not r['admission_authority']
    assert r['archive_measurement_at'] == a['measurement_at']


def test_current_cache_keeps_own_asof_and_fresh_free_space_probe():
    now = datetime.now(UTC)
    a = archive(now)
    r = capacity_status(a, service='collector', now=now, generated_at=now.isoformat())
    assert not r['backpressure'] and r['archive_measurement_is_cached']
    assert r['archive_measurement_at'] != r['observed_at']
    assert r['free_space_measured_at'] == now.isoformat()
    assert not r['admission_authority'] and not r['retirement_authorized']


@pytest.mark.parametrize('measurement', [None, 'not-a-time'])
def test_missing_measurement_timestamp_blocks_capacity(measurement):
    now = datetime.now(UTC)
    a = archive(now)
    a['measurement_at'] = measurement
    r = capacity_status(a, service='collector', now=now, generated_at=now.isoformat())
    assert r['backpressure'] and 'stale_capacity_observation' in r['alerts']


def render(c, e, view, *, width=40, height=40):
    out = StringIO()
    Console(file=out, width=width, color_system=None).print(
        render_monitor(c, e, view=view, width=width, height=height))
    value = out.getvalue()
    assert len(value.splitlines()) <= height
    assert all(len(row) <= width for row in value.splitlines())
    return value


@pytest.mark.parametrize('view', ['operations', 'archives', 'edge'])
def test_monitors_label_current_archive_samples_and_keep_safety(view):
    now = datetime.now(UTC)
    c, e = sample()
    c['archive'] = archive(now)
    e['archive'] = archive(now)
    e['operations_research']['phase18'] = {'status': 'research_only', 'last_evaluation_at': now.isoformat()}
    value = render(c, e, view)
    assert 'sample 10s' in value
    assert 'EXPERIMENTAL PAPER' in value and 'CERTIFIED PAPER' in value
    footer = 'LIVE FINANCIAL TRADING DISABLED' if view == 'archives' else 'LIVE TRADING DISABLED'
    assert footer in value


@pytest.mark.parametrize('width,height', [(30, 12), (40, 24), (80, 40)])
def test_narrow_operations_does_not_present_old_usage_as_current(width, height):
    now = datetime.now(UTC)
    c, e = sample()
    c['archive'] = archive(now, age=120, status='stale')
    e['archive'] = archive(now, age=120, status='stale')
    value = render(c, e, 'operations', width=width, height=height)
    if '3.0GiB' in value:
        assert 'STALE sample' in value
    assert 'LIVE TRADING DISABLED' in value


def test_archive_sample_unavailable_does_not_render_fake_zero():
    c, e = sample()
    for account in (c, e):
        account['archive'] = {'snapshot_only': True, 'measurement_at': None,
                              'measurement_status': 'unavailable', 'health': 'unknown'}
    value = render(c, e, 'operations')
    assert 'sample unavailable' in value and '0.0B/' not in value
