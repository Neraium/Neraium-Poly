# Phase30 memory
Owned data/store.py, data/segmented.py, test_phase30_memory.py only.

ActualOOMs17:21:24experimental and17:33:12collector; Phase29snapshot telemetry shows live malloc approximatelyflat(~97MB/~144MB) but free arena growing(~219->288MBcollector/22min,250->360MBexp/6min), not a proven retained-object leak. Nocap/GC/allocatorintervention.

Fixed demonstrated common append allocation churn: ManagedEventStore serialized sameRecord twice; now exact singleoriginaltext is validated and persisted intoactive segment andcatalog. CachedUTF8byte count avoids repeatedencode allocations forbudget/rotation/pending checks. Metadata extraction consumes and syntax-validates completeJSON plusfullSHA but ignoresnested evidence while materializing only exactid/event/availability/qualifiedmetadata. Original payloadbytes/hashes, strict admission, idcollision detection, boolclassification, crashorphan recovery andcoldreading unchanged. StandaloneEventStoreappendalso validates header beforewrite.

Actual immutable2,436,971-byte VolumeStudy benchmark30headerchecks: oldfullparse3,491,412peaktracedbytes/.8065s vs882bytes/.0371s, not live P/L or soleOOMcausalproof. Testsassertoneserialization, exactpersistedbytes/hash, duplicates/collision rollback, malformednestedJSON/headermismatch rejection, qualificationboolsemantics, originalrecovery.40focusedcases plusRuffpass. Evidence inphase30-memory.

Integration: cherry-pick commit; no runtimehookrequired. Rootdeployviaexisting authorizedserviceprocess. Long-run RSS/allocatortrajectory stillmustbeobserved; no indefiniteOOMeliminationclaim. No production/data/deploymentactions byworker.
