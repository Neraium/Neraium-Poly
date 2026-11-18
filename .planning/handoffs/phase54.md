# Phase 54 isolated market-frame replay

Base 5b92612. Compared serving experimental source 8d9756ff8a514ad87947646ffc330f0c3e10efc8 and Phase 53 instrumented source cf52778988d26e3d2016bb01cbfe85d212b3f64d (CI 44230763867). The replay processes use a common private loopback-only network namespace per arm. The source and live filesystem are protected, the live account/archive directory is inaccessible, and each arm has fresh disposable storage. Reference uses 1 CPU, 1 GiB and 64 tasks. Experimental uses 1 CPU, 2 GiB and 32 tasks. Production services were outside the replay.

## Matched workload

Fixture SHA-256 d20aaeaaf4fac66b04736aea8a54dabfa1a0f3935f1cbf67004fb1275ca2fdd3 covers the second Phase 52 window starting 2026-11-18 02:57:03.972731 UTC. Original archived book and market timestamps, identities and hashes were preserved. Reference quote deltas were reconstructed and checked with the production codec. A scoped public collector slab supplies genuine REST quotes between sparse retained reference snapshots. Each fresh process uses the same monotonic-to-historical clock mapping, server routes and native five-second sampler cadence. The initial view had 882 market identities and 761 cached books. Both initial arms processed 2,927 events and wrote 453 reference quotes to private managed archives.

The producer uses LivePaperRuntime.market_frame and the actual FastAPI endpoint, with native quote archive and midpoint work. The consumer runs the production ReferenceSampler and the actual report endpoint and verdict. It publishes an observation-only report when the sampler accepts a frame. No strategy scoring, financial accounts, or venue connections are loaded. The route timestamps the exported frame on the shared historical clock and the consumer preserves that timestamp without renewal. One initial poll in each arm preceded the first report. Cycles preserve the same 20-second dashboard rule and 15-second sampler check. The cache size approximates the retained Phase 52 producer shape. The native archive averaged far fewer fresh quotes per receipt than the live window, which relied on WebSocket updates. The fixture also lacks the whole production archive, concurrent risk reconciliation and the full shadow controller. Replay findings characterize the measured route, sampler and write load.

## What reproduced

The initial, undelayed arms recorded 0/61 timeouts for each revision and 59/60 fresh polls for each. The baseline wall latency was 455.24 ms p50, 558.09 ms p95, maximum 685.51 ms. Phase 53 instrumentation measured 435.74 ms p50, 505.22 ms p95 and maximum 690.31 ms. Every instrumented request joined a producer span with unchanged source timestamps. No matched request crossed the three-second HTTP read timeout.

The largest instrumented stage ran from completion of producer-frame construction to response headers (236.98 ms median, 261.77 ms p95). Client JSON decode took 144.12 ms median. Lock wait p95 was about five microseconds and frame construction under lock p95 was 7.92 ms. The test found redundant FastAPI traversal of the JSON-compatible producer payload. The review patch returns that payload through JSONResponse directly. The targeted regression reproduced the extra encoding on the old path and verified the same decoded frame, original quote timestamps, cache-control and content type after the change.

The isolated injected-delay control ran after the undelayed comparison. Request 1 failed while reading headers after 3.018 s, with the producer's final send 0.725 s later. Request 3 failed while reading the body after 3.296 s, with final send 0.439 s later. Both joined by request ID. These failures validate the tracing mechanism.

## Live evidence gap

Phase 52 observed 49 distinct reference requests behind the 54 timeout-associated polls. The isolated workload did not reproduce those failures. The retained live receipts lack paired client header/body timing and producer queue, lock, build and send stages. A minimum useful future capture is one genuine timeout bracketed by successful requests, joining the experimental request ID to the reference arrival and terminal send, and retaining producer logs beyond the client deadline to catch a late completion. A short bounded window on the same report-only traffic can stop once this triplet is captured. If there are no joined timeouts, the causal boundary remains open. Client-only telemetry can distinguish header versus body wait. Server-side attribution needs the instrumentation on the existing reference process and therefore requires a reference application restart. Use a separately reviewed instrumentation-only reference revision on its existing baseline. This is Craig's deployment decision.

## Matched repair result

| Five-minute isolated arm | Read timeouts | Request p50 / p95 | Fresh polls |
| --- | ---: | ---: | ---: |
| Serving 8d9756f | 0/61 | 455.24 / 558.09 ms | 59/60 |
| Instrumented cf527789, before | 0/61 | 435.74 / 505.22 ms | 59/60 |
| JSONResponse repair 56fdb8b, after | 0/61 | 254.16 / 313.20 ms | 59/60 |

All three arms processed 2,927 scheduled updates and archived 453 native reference quote updates. The repair reduced instrumented median handler-to-headers time from 236.98 to 50.21 ms (78.8%) and p95 from 261.77 to 63.92 ms. Client decode medians were 144.12 and 147.33 ms. The repaired maximum request was 322.95 ms. Both traced arms joined 61/61 request IDs. The experiment demonstrated savings on the tested route workload. The Phase 52 live timeout cause and any live freshness effect remain open.

Implementation 56fdb8be1f1ff6620922f947daf7e88b519a71da passed 34 focused tests, Ruff and exact-source backend and dashboard CI 44233071376. The branch carries the verified compressed input, trace logs, join and calculation code. A same-host rerun can stage the fixture to a new private scratch directory, write its path to scratch.local, and invoke run.sh a b d. The c arm separately runs the injected positive control. The original setup probe correctly encountered an inaccessible live data path. The harness was corrected to recognize the expected permission error before the matched runs began. No unsuccessful startup probe contributed any timed requests.

Production read-only attestation matched Phase 53 exactly. Experimental PID 788797 remains on 8d9756f with shadow quiesced and stop latched. Reference PID 555731 continued running unchanged. Both accounts had zero positions and unreleased reservations. No activation took place.
