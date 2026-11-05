# Execution eligibility boundary

Only paper execution is implemented and authorized. No wallets, transaction submission, deposits, pooled capital or funded execution are supported. A future release needs separate explicit authorization and jurisdiction-specific legal review, including ownership/control, account eligibility, sanctions, age and applicable registration obligations.

Primary sources inspected 2026-11-05: [Polymarket Terms of Use](https://polymarket.com/tos) (effective August 11, 2026) restrict trading by specified persons and jurisdictions, including residence, location and entity control; they prohibit circumvention with VPNs. [Geographic Restrictions](https://docs.polymarket.com/api-reference/geoblock) documents the public eligibility endpoint and rejection of blocked orders. IP geoblock results alone do not establish personal, entity or legal eligibility. No eligibility conclusion is made for this AWS host or its operator. These requirements must be rechecked before any separately authorized future live-release proposal.

Public data collection is read-only. Fee models use [current protocol fee documentation](https://docs.polymarket.com/trading/fees) as an explicitly supplied research parameter. The model does not infer fee-free status from a market name or category, and no current fee schedule is hardcoded as universal.
