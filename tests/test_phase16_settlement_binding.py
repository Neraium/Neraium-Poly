"""Controlled official-source fixtures; no fixture outcome is real evidence."""
import asyncio
import copy

import httpx
import pytest
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from test_phase12_outcome_collector import NOW, controlled_clients


def clients(change=None):
    f, m, original, rpc = controlled_clients()
    handler = original._transport.handler
    requests = []
    def wrap(request):
        requests.append(request.url.path)
        if request.url.path == '/markets/1':
            response = handler(request)
            raw = response.json()
            raw.pop('eventId', None)
            raw.pop('events', None)
            return httpx.Response(200, json=raw)
        if request.url.path == '/events/event-1':
            raw = handler(httpx.Request('GET', 'https://gamma-api.polymarket.com/markets/1')).json()
            raw.pop('eventId', None)
            parent = {'id': 'event-1', 'markets': [raw]}
            if change:
                change(parent)
            return httpx.Response(200, json=parent)
        return handler(request)
    return f, m, original, httpx.AsyncClient(transport=httpx.MockTransport(wrap)), rpc, requests


async def test_missing_detail_parent_requires_real_membership_and_full_native_chain_replay(tmp_path):
    f, m, original, public, rpc, requests = clients()
    try:
        outcome = await acquire_verified_outcome(f, m, tmp_path/'evidence', client=public, rpc_client=rpc, clock=lambda: NOW)
        assert outcome is not None
        assert requests == ['/markets/1','/events/event-1','/markets-by-token/11','/v2/resolutions']
        assert await asyncio.to_thread(verify_collected_outcome, outcome, m, f, tmp_path)
    finally:
        await original.aclose()
        await public.aclose()
        rpc.close()


@pytest.mark.parametrize('change', [
    lambda p: p.update(id='different'),
    lambda p: p['markets'].clear(),
    lambda p: p['markets'].append(copy.deepcopy(p['markets'][0])),
    lambda p: p['markets'][0].update(conditionId='different'),
    lambda p: p['markets'][0].update(description='different rules'),
    lambda p: p['markets'][0].update(clobTokenIds='["12","11"]'),
    lambda p: p['markets'][0].update(negRisk=True),
])
async def test_parent_contradictions_or_ambiguity_never_become_verified_outcome(tmp_path, change):
    f, m, original, public, rpc, requests = clients(change)
    try:
        assert await acquire_verified_outcome(f, m, tmp_path/'evidence', client=public, rpc_client=rpc, clock=lambda: NOW) is None
        assert len(requests) == 2
    finally:
        await original.aclose()
        await public.aclose()
        rpc.close()


@pytest.mark.parametrize('field,value', [('question', 'Different outcome question'), ('end_time', NOW)])
async def test_forecast_question_or_window_must_match_current_verified_contract(tmp_path, field, value):
    f, m, original, public, rpc, requests = clients()
    try:
        changed = m.model_copy(update={field: value})
        assert await acquire_verified_outcome(f, changed, tmp_path/'evidence', client=public, rpc_client=rpc, clock=lambda: NOW) is None
        assert requests == ['/markets/1', '/events/event-1']
    finally:
        await original.aclose()
        await public.aclose()
        rpc.close()
