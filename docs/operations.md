# Local operations

`uv sync --extra dev` installs locked backend dependencies. `uv run neraium-poly scenario` executes the complete deterministic synthetic research workflow. `uv run neraium-poly serve` binds the operational service to 127.0.0.1:18740. Build the dashboard with `cd frontend && npm ci && npm run build`; the service serves this build when run from the repository root. Development uses `npm run dev` (loopback port 18741, proxy to port 18740).

The replay button runs a deterministic synthetic scenario, never live orders. The emergency stop latches for this runtime; there is no browser reset. Restart only after review. Dashboard snapshots label synthetic data and simulated P/L. API unavailability is displayed; stale last snapshots cannot authorize execution. No automatic model promotion, exchange wallet, secret input, or funded execution is present.

This unauthenticated service is for loopback single-user research only. Do not expose it on a public interface. External operation requires separate authentication, deployment and security design. Cross-origin browser mutations are rejected. Persistent public collection is separate from the in-memory reference scenario. Initial reference scenario restarts do not represent durable real-world portfolio operation.
