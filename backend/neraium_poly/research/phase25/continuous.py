"""Versioned expansion enrollment reusing the frozen Phase24 research engine."""
import importlib
from pathlib import Path
from types import SimpleNamespace

from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.continuous import DomainResearch, DomainResearchStudy
from neraium_poly.research.phase24.outcomes import DomainOutcomes, DomainOutcomeStudy, replay_domain_outcome


class ExpansionResearchStudy(DomainResearchStudy):
    """Separate immutable namespace; never replaces an earlier enrollment."""


class ExpansionOutcomeStudy(DomainOutcomeStudy):
    """Verification/checkpoint namespace belonging only to expansion forecasts."""


class ScopedStore:
    def __init__(self,store):self.underlying=store
    def latest(self,kind,limit=100):
        physical={'DomainResearchStudy':'ExpansionResearchStudy','DomainOutcomeStudy':'ExpansionOutcomeStudy'}.get(kind)
        return latest(self.underlying,physical,limit=limit) if physical else []
    def get(self,identity):return self.underlying.get(identity)
    def append(self,record):
        cls=ExpansionResearchStudy if isinstance(record,DomainResearchStudy) else ExpansionOutcomeStudy if isinstance(record,DomainOutcomeStudy) else None
        if cls is None:raise ValueError('expansion namespace rejects unrelated record')
        row=cls.model_validate(record.model_dump()).model_copy(update={'source':record.source.replace('/v24','/v25')})
        return self.underlying.append(row)


def modules():return {name:importlib.import_module('neraium_poly.research.phase25.'+name) for name in ('finance','economics','sports','weather')}


class SourceAdapter:
    def __init__(self,module):self.module=module
    def __getattr__(self,name):return getattr(self.module,name)
    async def forecast(self,*args,**kwargs):
        result=await self.module.forecast(*args,**kwargs)
        return {**result,'rejections':[str(x) if str(x).strip() else 'source_unavailable_without_provider_detail' for x in result.get('rejections',[])]}


class ExpansionResearch(DomainResearch):
    def __init__(self,store,*,adapters=None,**kwargs):
        selected={name:SourceAdapter(module) for name,module in (modules() if adapters is None else adapters).items()}
        # The inherited enrollment already fingerprints each module file. Include
        # this namespace/selection policy without declaring a fictional model.
        for name,path in (('_integration_policy',Path(__file__)),('_discovery_policy',Path(__file__).with_name('discovery.py'))):
            selected[name]=SimpleNamespace(__file__=str(path),definitions=list,supports=lambda *a,**kw:{'supported':False,'reasons':[]})
        super().__init__(ScopedStore(store),adapters=selected,**kwargs)


class ExpansionOutcomes(DomainOutcomes):
    def __init__(self,store,directory,**kwargs):super().__init__(ScopedStore(store),directory,**kwargs)
    def _module(self,adapter):
        if adapter not in ('finance','economics','sports','weather'):raise ValueError('unsupported expansion outcome adapter')
        return modules()[adapter]
    def _replay(self,row,study,forecast,*,evidence_root,as_of):
        return replay_domain_outcome(row,study,forecast,evidence_root=evidence_root,as_of=as_of,modules=modules())
