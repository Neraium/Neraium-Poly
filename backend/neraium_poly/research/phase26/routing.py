"""Strict outcome routing beside unchanged forecasting models and checkpoints."""
from datetime import timedelta

from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase24.outcomes import DomainOutcomes, replay_domain_outcome
from neraium_poly.research.phase25.continuous import ExpansionOutcomes, modules


class SportsProofs:
    def __init__(self,original):self.original=original
    def __getattr__(self,name):return getattr(self.original,name)
    async def verify_outcome(self,forecast,*,directory,clock):
        if forecast.get('league')=='NHL':
            from neraium_poly.research.phase26.outcomes import verify_sport_outcome
            return await verify_sport_outcome(forecast,directory=directory,clock=clock)
        return await self.original.verify_outcome(forecast,directory=directory,clock=clock)


class OfficialDomainOutcomes(DomainOutcomes):
    def _module(self,adapter):
        original=super()._module(adapter)
        return SportsProofs(original) if adapter=='sports' else original
    def _due(self,p,now):
        return now>=at(p['end'])+timedelta(hours=1 if p['adapter']=='sports' else 4 if p['adapter']=='legacy_nfl' else 0)


class OfficialExpansionOutcomes(ExpansionOutcomes):
    def _module(self,adapter):
        original=super()._module(adapter)
        return SportsProofs(original) if adapter=='sports' else original
    def _due(self,p,now):return OfficialDomainOutcomes._due(self,p,now)
    def _replay(self,row,study,forecast,*,evidence_root,as_of):
        return replay_domain_outcome(row,study,forecast,evidence_root=evidence_root,as_of=as_of,modules=modules())
