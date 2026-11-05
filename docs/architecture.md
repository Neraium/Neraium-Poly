# Architecture v1

A modular Python monolith with immutable Pydantic contracts and a React/TypeScript operations console. Data → relationship evidence → calibrated estimate → net-value opportunity → atomic risk reservation → paper broker → reconciliation → operational API. All records distinguish event time and availability time. Replay uses availability order and stable IDs.

Modules: data (A), intelligence (B), strategy (C), execution (D), risk (E), ops + frontend (F). Shared contracts are owned by integration. Agents may add module-local types but cannot edit contracts without coordinator review. Public API readers require no credentials; no live order transport exists. Fail closed on missing rules, unknown fees, stale data, unavailable risk, and unknown evidence.

Initial persistence uses SQLite WAL append-only event records and transactional state for portable research. PostgreSQL migration is required before multi-process production operation; there is no measured scale requirement for a database server yet. A single process owns the paper portfolio. Performance claims require reproducible out-of-sample evidence.

All six workstreams branch from the foundation commit. A/B/E build first concurrently; C/D follow their reviewed interfaces. F is built by integration concurrently. Three workers maximum. Keep all other Neraium services intact.

Exit conditions: contracts validate; all subsystem tests pass; deterministic complete paper flow runs; risk boundaries hold; frontend type/build/browser checks pass; dependency checks recorded; implementation committed and pushed. Missing certification remains explicit and blocks a complete claim.
