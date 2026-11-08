# Authorized 200/200 GiB capacity review — blocked
2026-11-08 UTC, /home/ubuntu/Neraium-Poly, main, baseline2c65d18. Read-only review; no configuration, systemd, AWS, data, trading or stop changes.

Observed available450.70GiB, combined archives25.05GiB. Fully consuming requested400GiB would leave75.75GiB, short of the100GiB floor by24.25GiB even before additional existing temporary/shared-growth headrooms. Existing Phase18 capacity planner rejects targets_cannot_preserve_protected_free_reserve; with8GiB temporary+64GiB shared-growth protection, deficit96.25GiB. No lower quota applied: user explicitly required unchanged limits on unsafe expansion.

Active/persistent quotas remain collector200GiB and experimental100GiB; both100GiB reserve, retain-all originals. Experimental config schema currently has128GiB upper bound; not changed while capacity prerequisite fails. Existing strict admission fails closed on service budget/global floor. Observed growth50,351/83,104bytes/s gives conditional current-budget runways45.19/13.74days, not guarantees.

Five focused capacity/floor/recovery/corruption/config-isolation tests passed. Both account risk/broker quick_checks passed, config file hashes unchanged, both services active with same PIDs/resources; no restart needed. Paper balances500/496.11522059829053, live submission disabled. Evidence .planning/evidence/archive-capacity-review/. Additional usable headroom or different limits require a separately authorized solution; no deletion/migration/spending attempted.
