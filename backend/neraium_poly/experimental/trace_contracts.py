"""Phase10 decision-trace vocabulary; no admission or risk-policy authority."""

from typing import Literal

Category = Literal[
    "BUG",
    "MISSING EVIDENCE",
    "MARKET CONDITION",
    "RISK REJECTION",
    "STRATEGY LIMITATION",
    "CERTIFICATION DEPENDENCY",
]
STAGES = (
    "markets_considered",
    "valid_observations",
    "candidate_signals",
    "rejected_signals",
    "qualified_opportunities",
    "risk_rejections",
    "order_attempts",
    "submitted_orders",
    "fills",
    "expired_orders",
    "cancelled_orders",
)
COUNTER_SCOPE = {
    "phase10_epoch": "Cumulative since explicit trace epoch; persisted across restart; legacy counts retained separately",
    "latest_cycle": "Latest completed experimental cycle; replaced on each completed cycle",
    "strategy_id": "Each strategy has independent counters; rejected reasons are nonexclusive and do not sum to rejected signals",
    "candidate_signals": "Data/evidence prerequisites passed with a numerical valuation; cost/risk can still reject",
    "qualified_opportunities": "Strategy admission predicates passed before portfolio risk",
    "order_attempts": "A paper order intent was created and presented to risk; not all qualified opportunities create an intent",
    "fills": "New simulated execution fill events including partials; entries/exits reported separately",
}
