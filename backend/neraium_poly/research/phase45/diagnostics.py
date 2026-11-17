"""Exact rejection classification; old mixed reasons remain mixed, not invented."""
from collections import Counter


def category(reason):
    if reason in ('net_hypothesis_or_native_minimum_size','bid_history_and_verified_fees_required','complementary_native_identity_or_fee_evidence_unverified','bid_trend_does_not_cover_round_trip_friction_and_depth'):
        return 'historically_ambiguous_evidence_or_economics'
    if 'fee' in reason and any(v in reason for v in ('missing','unavailable','unverified','invalid','stale')):return 'missing_verified_fees'
    if any(v in reason for v in ('source_forecast','external_evidence','history','revision','model_identity')):return 'missing_independent_evidence'
    if any(v in reason for v in ('book','stale','future','price_tick')):return 'invalid_or_stale_book'
    if any(v in reason for v in ('minimum','depth','quantity','liquidity','budget_too_small')):return 'insufficient_executable_quantity'
    if 'spread' in reason:return 'spread_too_wide'
    if any(v in reason for v in ('calibration','uncertainty')):return 'probability_uncertainty'
    if any(v in reason for v in ('condition','structure','settlement','outcome_identity','contract_identity','pair')):return 'unsupported_or_unverified_market_structure'
    if any(v in reason for v in ('exposure','correlation','risk','loss_stop','suspended','already_enrolled','retired','legacy_cohort')):return 'portfolio_or_research_policy'
    if any(v in reason for v in ('edge','profit','friction','net_hypothesis','payout','trend','imbalance')):return 'unfavorable_economics_or_signal'
    return 'other_explicit_reason'


def breakdown(rejections):
    counts=Counter()
    for key,count in rejections.items():counts[category(key.split(':',1)[-1])]+=count
    return {'observations':dict(counts),'total':sum(counts.values()),
            'unit':'repeated rejection observations in one alternative profile; not unique opportunities or independent events',
            'legacy_ambiguity':'Mixed historical reasons cannot be causally separated with the evidence retained; new decisions use separate reasons.'}
