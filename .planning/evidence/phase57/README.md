# Phase 57 paper observation

The Phase 56 audit found all 900 token requests present. The four threshold markets returned complementary one-sided books and sometimes stale exchange timestamps. No missing subscriptions or incomplete depth fields were found.

`freeze.json` admits only same-condition complete sets. Selection used pre-score market metadata and recent fresh two-sided books with minimum order depth. Eligible markets stay in the denominator for the entire capture. The capture uses concurrent public GETs every five seconds with a three-second deadline, a 2 GiB compressed-tape cap and a 1 GiB buffer above the 100 GiB reserve. The raw tape stays on the host.

`score.py` calls the unchanged Phase 56 scanner. Priceable hours are sampled estimates based on at least one executable direction with minimum depth. A valid sample contributes up to one interval and gaps longer than 1.5 intervals contribute no coverage. An episode starts at the first positive-gross observation and ends at interruption or loss of gross edge. Duration is the first-to-last observed span. Sub-poll persistence is unmeasured. Each episode retains distinct depth configurations and links to modeled attempts. The frozen latency model uses subsequent sampled books, so the tape does not resolve events between polls. Conversion is unverified. The ten-cent sensitivity applies to modeled attempts only and cannot qualify them as verified executable opportunities.

Validation reused the Phase 56 failure checks and replayed a four-poll capture prefix separately. The prefix is a smoke test and is excluded from results. No service configuration, journal, account or trading path was changed.
