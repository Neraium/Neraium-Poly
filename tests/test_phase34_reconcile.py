"""Filtered reconciliation keeps all cumulative acknowledgements and fails closed."""
import json

import pytest
from neraium_poly.execution import ExecutionConfig, PaperBroker
from neraium_poly.risk import RiskEngine
from test_execution import approved


def test_sql_filter_preserves_order_and_all_original_history(now):
    risk=RiskEngine()
    try:
        for i in range(1000):risk._audit('experimental_mark',{'i':i},now)
        risk._audit('fill',{'reservation_id':'old'},now)
        risk._audit('fill',{'reservation_id':'new'},now)
        old=risk.audit();assert len(old)==1002
        assert risk.audit(action='fill')==[r for r in old if r['action']=='fill']
        assert risk.audit()==old
        assert risk.audit(action="fill' OR 1=1 --")==[]
    finally:risk.close()


@pytest.mark.parametrize('corruption',['none','mismatch','orphan','unavailable'])
def test_fill_only_reconcile_keeps_mismatch_orphan_and_failure_checks(now,market,book,monkeypatch,corruption):
    risk=RiskEngine();broker=PaperBroker(risk,config=ExecutionConfig(latency_ms=0))
    try:
        intent,decision=approved(now,market,book,risk)
        broker.submit(intent,decision,book,now=now)
        for i in range(1000):risk._audit('experimental_mark',{'i':i},now)
        last=json.loads(risk.audit(action='fill')[-1]['payload'])
        if corruption=='mismatch':risk._audit('fill',{**last,'quantity':last['quantity']+1},now)
        if corruption=='orphan':risk._audit('fill',{**last,'reservation_id':'orphan'},now)
        old=risk.audit
        def filtered_only(*,action=None):
            assert action=='fill','must not materialize unrelated historical marks'
            if corruption=='unavailable':raise OSError('controlled unavailable risk audit')
            return old(action=action)
        monkeypatch.setattr(risk,'audit',filtered_only)
        result=broker.reconcile(now=now)
        assert result['consistent']==(corruption=='none')
        if corruption=='mismatch':assert intent.client_order_id in result['mismatches']
        if corruption=='orphan':assert 'orphan-risk-fill:orphan' in result['mismatches']
        if corruption=='unavailable':assert 'risk_audit_unavailable' in result['unavailable']
    finally:broker.close();risk.close()
