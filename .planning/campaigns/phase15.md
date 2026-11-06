# Phase15 sustainable archives and research readiness

Status: delivered; owner stop/retention decisions and evidence qualification remain blocked. Baseline3b41ee5, source8e1c68e,main,/home/ubuntu/Neraium-Poly.
2026-11-06 20:22UTC:32logicalCPU,236GiBavailableRAM,513735028736Brootfree,load0.76.
Bothaccounts500/PnL0; sourcecollector/experimentalarchiveshealthy; collectorhealth
momentarilydegradeddespiteingestion0.06sage requiresfreshnessinvestigation. Original
untrackedEBS/liveinspectionevidencepreserved. No AWSresource/chargechanges.

## Shared contracts and ownership
Archiveagent: backend/neraium_poly/data/cold.py,tests/test_phase15_cold.py,
docs/phase15-retention.md ONLY. Implement independentlyverifiedrestore/cache and
immutablecoldproofs; catalog-awareinventory/retentionproposal exactpaths/hash/bytes,
explicit ownerauthorization required, NO ORIGINAL DELETION FUNCTION. Active/warm/
coldclassificationseparatesverifiedcompressedrepresentation fromraw eligibility.
Tests mayremovecontrolledfixtureoriginalstoexercisecold-onlyreader. Production
originalsneverremoved. No move/compress/replaceopenSQLitewriter. Managedcore owned
coordinator; integrateoptionalcoldverificationafterreview. API contracts:
inventory(directory,*,now,warm_seconds)->dict;
verify_cold_segment(raw_path,*,catalog_row,cache_directory,min_free_bytes,max_cache_bytes)->dict;
retention_proposal(directory,*,now,warm_seconds,retention_class)->dict with exact
paths/rawsha/gzipsha/manifestsha/records/device/inode/bytes andapproval_required=True,
removal_authorized=False. Coldproof includes independentSQLitequick_check,perrecord
digest,count andgziproundtrip, testedrecovery, rawnotmodified. Cacheonlyderivedcopies
mayevictifnotpinned andverifiedoriginal/copyremain. No retentionpolicyselfapproval.

Domainsagent: research/phase15/domains.py (+__init__.py),tests/test_phase15_domains.py,
docs/phase15-domains.md ONLY. Independentresearchadapters/qualificationprogress,
legitimateprimarysources, boundedrealacquisition, causalcalibrationgate. No edits
existingregistry/tradingadmission. Allnewmodelsresearch_only; probabilitiesNone
unlessgenuineevidencequalified. Reportactualsource/times/hash/missingness. Preserve
sports. Agentsource JSONevidence uses existingDomainEvidence/DomainContract shapes.

Riskagent: research/phase15/readiness.py,tests/test_phase15_readiness.py,
docs/phase15-stop-readiness.md ONLY. Read-onlyliveauditoriginalkillcause/timestamp,
strategyreadiness6entries, correlatedrisk/accountintegrity. No reset call orrisk
codechange. Produce source-boundrecoveryassessment andownerapprovalrequest, no
resetuntilnewexplicitauthorization. Do not confuselogicalreadinesswithcertification.

Coordinator: phase15/budgets.py,SII/historyresearch,configs/runtime/terminaloperations
view,integration/testing/CI/soak. Threewritingagentsinseparatenativeworktrees
poly-p15-{archive,domains,risk}-20261106; maxtwoCPUanalysis/testworkers, preserve
livecollector1CPU/1GiBandexperimental0.5CPU/768MiBunits. No budgetincreaseblindly.
Keep64GiB/16GiBcurrently,64GiBoperatingreserveincluding8GiBhardfloor. Capacity
projectionsmustincludeever-growingcatalog/state notjustgzipratios. Months under
retain-all finitebudgets cannotbeguaranteed; exactownerpolicy/budgetproposalfirst.

## Phase End Conditions
|Phase|Status|Condition|validator_retries_remaining|
|baseline/contracts|complete|actualservices/records/resourcesverified|3|
|parallelimplementation|complete|coldproof/domainqualification/stopassessment implemented+tests|3|
|integrate|complete|budgetalerts/operationsview/SII/historyresearch integrated|3|
|verify|complete|backend/browser/replay/failure/audits/CIpass|3|
|operate|complete|necessaryrestart,boundedactualsoak,accounts/journals/latchpreserved|3|
|deliver|complete|commit/push,handoff,exactapprovalrequests|3|

## Exit Evidence
|Target|ID|Type|Required|Evidence|Status|Subject|
|phase:verify|tests|command_passes|yes|.planning/evidence/phase15/verification.json|pending|phase15source|
|phase:operate|soak|file_exists|yes|.planning/evidence/phase15/soak.json|pending|actualpublicdata|

## Current resumable checkpoint
Source8e1c68e committed/pushed; GitHubCI42291947924 success.921backendtests
(2realconcurrenttestprocesses),5Playwrightbrowserchecks,Ruff,build,Python/npm
auditsallpass. SeparateProcessPoolanalysisworkers3183147/3183150weregenuinely
concurrentfor.0416s; mostlyIO,not2saturatedCPUs. Maximum4agentsincludingroot,
3isolatednativewritingworktrees;noadditionalagentsnested.
OnlyPolyservicesrestarted20:52UTC. CurrentPIDs3185204collector/3185205exp.
Firstfreshcollector20:53:19approximately; servicecoveryverified20:53:28.
Actualsoakdata/phase15/soak.py(session7125)31samples20sapart20:53:35–21:03:35UTC.
Pending: finishsoak,verifyallpreexistingimmutablefilesandjournalprefixes,derive
capacity/report/readinessownerassessment,exactretentionproposal0eligibleoriginals,
finalcommittedreport/evidence/handoff/memorysync/push. No reset ororiginaldeletion.
Config64/16GiBbudgets,64GiBreserve,automaticcoldproof1/min,continuousSII20s.

OriginaluntrackedEBS/liveinspectionevidencepreserved; READMEnewoperationslinkpending.

## Delivery evidence
Soak600.50seconds/31healthyof31,200markets/296freshbooks at21:03:36UTC.
Bothcash500/PnL0/0orders/fills/positions. Experimentalstoptrue; certifiedgateblocked.
3newshort_horizonsignalsat20:54rejectedsolelykill_switch,5lifetimeattempts.
Collector+3seals/+4gz/+7proofs,+19361records; exp+4/+4/+10,+5078records.
510pre-existingimmutablefilesSHAverified;alljournalprefixesintact.
Finalsourceboundassessment09451a2fca2d30e3e628019cea944cf1d163cabed9efdaa74332b9c4d6d845bb
technicalcheckspass,noreset authority. No originaldeletion;0retentioncandidates.
See docs/phase15-readiness.md and .planning/evidence/phase15/.
