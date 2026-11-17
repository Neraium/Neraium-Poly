"""Close superseded empty-cohort entry enrollment without resetting its ledger."""
import copy

from neraium_poly.research.phase44.cohort import Cohort


class ClosedPhase44(Cohort):
    entry_enrollment_open=False
    def close_enrollment(self):
        if self.last and self.last['policy'].get('entry_enrollment_open'):
            self._commit(copy.deepcopy(self.state),[{'type':'enrollment_closed','reason':'superseded exploratory hypotheses; all original forecasts, positions, cash, stops and negative results retained'}],{'operation':'close Phase44 new-entry enrollment'})
    def needs_quotes(self):
        return any(s['orders'] or s['positions'] for s in self.state['profiles'].values()) or any(a['positions'] for a in self.state.get('exit_tournament',{}).get('arms',{}).values())
