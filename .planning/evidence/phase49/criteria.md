# Phase 49 measurement criteria

Use consecutive 300-second windows with Phase 48's serial health/research requests and five-second sleep. Include failed polls and stale reports. Start post-deployment windows at readiness, with the startup trace separate. Count reports as fresh only when the API marks them fresh. Show unique source frames and report publications separately. Historical source IDs or publication timestamps that the runtime did not expose must be marked unavailable.

Success requires intact paper-only gates, original timestamp and health semantics, no stale-book admission, and a higher fresh fraction in each corresponding post-deployment window to claim sustained improvement across the sample. Record reference timeouts, degradation, and post-read latencies even if the result is mixed. Keep all windows.
