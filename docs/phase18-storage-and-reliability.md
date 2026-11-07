# Phase 18 archive budget and runway

The measured root ext4 capacity is1,038,993,555,456 bytes (~967.64 GiB), not an extra
cloud-volume change. The200 GiBcollector /100 GiBexperimental targets are existing-root maximum
usage budgets, not preallocated files. All service-root active/warm/cold/temp/hidden/manifest
files are counted; current other-project usage is already deducted from available space.

Capacity admission uses current free minus incremental maximum service growth,8 GiB temporary
rotation/restoration allowance and 64 GiB shared-workload growth allowance. The remaining space
must still exceed the protected100 GiB floor. Live per-write global checks remain required since
unrelated future growth is unconstrained. Snapshot admission cannot promise otherwise.

The actual systemdExecStart JSONs named`config/paper-live.example.json` and
`config/experimental-paper.example.json` now specify204800/102400 MiB budgets. Both
min_free_disk_mb and archive_reserve_disk_mb are102400 MiB. Managedmode stays enabled.
Financial settings are byte-for-byte equal to their before configurations. Collector config
validation now accepts up to262144 MiB; experimental existing upper bound already accepts100 GiB.

Separate advisory allocations (GiB) are collector active1/warm40/cold100/catalog43/protected16,
experimental active0.5/warm20/cold48/catalog23.5/protected8. These do not authorize deletions or
replace the all-file hard budget. Original64/16 tier defaults remain for other configurations.

| Service | Prior cap GiB | New cap GiB | Observed net bytes/s | Sub-day window hours | Conditional days to cap |
|---|---:|---:|---:|---:|---:|
| collector | 64 | 200 | 109923.97 | 3.61 | 21.59 |
| experimental | 16 | 100 | 60820.84 | 3.61 | 19.76 |

These2026-11-07~04:04 UTC estimates use~3.6 hours of genuine retained growth and are not
representative24 hour rates. They already include normal compression with originals retained.
Short post-restart growth measurements are reported separately in operational evidence; startup
catalog/WAL checkpoints can produce transient negative net deltas and do not prove zero growth.

Compression alone cannot make retain-all-originals bounded indefinitely. A hypothetical removal
of only future warm growth after fully verified cold transition would reduce measured net growth,
but existing catalog/state/protected growth would continue. It is not an authorized or guaranteed
months-long policy. The separate exact retention proposal retains originals pending explicit owner
approval, successful restore/completeness proof, age and complete process-reference checks.

Large unrelated directories were measured read-only and left untouched. Partialdupermission
coverage is documented; filesystemf_bavail accounts for inaccessible consumption. No cache cleanup,
AWS modification, infrastructure spend or new persistent volume occurred.

Existing restart recovery reindexes all retained source segments under the original CPUquota.
Collector startup took roughly3 minutes in this deployment; larger archives will increase recovery
latency unless future verified-checkpoint/index work reduces it without weakening integrity.
The all-original full-index restart cost is a Phase 19 reliability concern, not hidden downtime.
