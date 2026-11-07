# Phase 17 empirical edge and research infrastructure
Status: complete
Baseline12c762c, main, /home/ubuntu/Neraium-Poly; origin/main synchronized.
Existing untracked EBS/recovery evidence preserved. No live trading, stop reset, risk increase,
strategy edit/promotion, original deletion/retention change or infrastructure spend.
Resource baseline32logicalCPUs/~237GiBavailableRAM/~476GiBfree;servicequotas1/.5CPU.
Use3isolatedwritingagents+coordinator;coordinatoranalysis/testsmax2processworkers.

## Shared integration contracts and exclusive ownership
A economics+strategydiagnostics: NEWphase17/economics.py,diagnostics.py,
tests/test_phase17_economics.py,docs/phase17-execution-notes.md.
Cost API evaluate_roundtrip(decision,label,*,quantity=5,fee_multiplier=1,slippage_per_leg=.01,
latency_seconds=.1)->dict. Points arePhase16CausalHistorypointdicts; labelobservedsource
must bepost-ready/predetermined60shorizon,matchingtoken/market/event/rules,depth25%max,
actualobservedaskentry/bidexit, source/receipt15s atrespectivecausalcutoffs, qualifiedfees.
Returns fullfill ORexplicitunexecutable, gross/net/fees/slip/capacity/provenance; hypothetical
researchoutcomes NEVERoperationalfills/accountPnL. No fallbackunavailablefees/depth.
Diagnostics purefunction summarize_rejections(rows,*,verify_row=None)->dict; noauthorization.

B statisticalmodelresearch: NEWphase17/statistics.py,models.py,
tests/test_phase17_statistics.py,docs/phase17-methodology.md.
API evaluate_experiments(rows,*,training_end,validation_end,cutoff,verify_row=None)->dict.
Rows eachcontain id,event_id,token_id,decision_at,label_available_at,target_at, actual_bid,
baseline, forecasts{candidate:prediction}, costs{gross_per_share,net_per_share,...}, provenance.
Sourceverificationcallbackdefaultdeny. Chronologicalfit/frozenparams;90spurge,nonoverlap
60sepisodesperparentacrosstokens;reportparentoverlap/effectivegroups. Separateexploratory
chronologicaldiagnostics fromSTRICTevent-disjointheldout. No probabilitymetricsforUSDmarks.
Dependence-awarebootstrap+Holmfamilycorrectiononlywithadequate independentlyreviewedgroups,
otherwiseCIs/pvaluesnullwithreasons. No certification/tradingauthority. Fixedcandidatefamily
unchangedbid/reversion20/momentum20/depthimbalance;no postholdoutparamselection.
ModelAPI causal_forecasts(points,*,cutoff)->list[dict] output originaldecisionpoint id,
prior-only forecasts andfeature provenance; no heldoutlabel fitting.

C provenance+storage: NEWphase17/provenance.py,storage.py,
tests/test_phase17_integrity.py,docs/phase17-integrity-notes.md.
ReadonlyArchive(path) readlatest/readbyid verifiescatalog+payloadSHA, boundedframes,
nonmutatingnativeSQLiteROconnections only, NOManagedStoreowners,noDBreplacement/noextract
activeDB,nooriginaldeletion. Support existingrawsegments; missingrawrejectexplicitly.
API latest(kind,limit=100),get(id), close. Includeverify_study rawframe andsourcebinding
wherepossible; no synthetictruthcallback. Storage measurement/retentionclasses/redundant
DERIVEDdataforecast/proposal+recoveryverificationwithoutdeletion; sourcehashes preserved.

Coordinator ownsruntime/config,phase17/continuous.py,__init__.py,monitor,dataextraction,
authenticfrozenexperiments,sourceCI+integration,finalrequiredreports. Nevereditphase16
continuous/history/relationships/execution/readiness/checkpoints code: existingcheckpoint
codehash must continue recovery unchanged. ConsumePhase16committedstudies/history and
appendderivedresearchrecords toexistingManagedStore;no competingcollector/subsystem.

## Phase End Conditions
|Phase|Status|Condition|validator_retries_remaining|
|baseline|complete|actualsource/state/account/integrity/resourcescaptured|3|
|build|complete|isolatedreviewedcommits+focusedtests|3|
|experiment|complete|authenticprovenance+causalpurgedbaselineartifacts|3|
|verify|complete|backend/browser/audits/sourceCIpass|3|
|operate|complete|>=600srealsource/recovery/accountpreservation|3|
|deliver|complete|6requireddocuments+commit/push|3|

## Exit Evidence
|Target|ID|Type|Required|Evidence|Status|Subject|
|phase:verify|tests|command_passes|yes|.planning/evidence/phase17/verification.json|complete|phase17source|
|phase:operate|actual|file_exists|yes|.planning/evidence/phase17/operation.json|complete|genuinepublicdata|

## Completion 2026-11-07T00:29UTC
Source362d58f(main+origin),core49cd0b0,collectorPID3185204unchanged,experimentalPID3226049.
CI42317888416green1119backend+5browser,local1118parallel+20monitorregressions,auditsgreen.
Preregistered181studies/1094points/972marks/816rows;53train6val20temporalheldout,
0eventdisjointheldout/0reviewedgroups.0costselected,imbalanceworse,otherstieflatbaseline.
Genuinelivemarkresearch88forecastpoints/75matured/11pending/2expired,19updates;
606secondsoak30/31healthy;producerdegradedcyclewithheld00:19:17,nextcycle00:19:24recovered.
NoPhase17orders/fills/PnLdelta,experimental498.73125,totalrealized-1.26875,certified500/0;
0positions/exposure/reservations,stopclearnoreset,certapprovalblocked,LIVEfalse.
796baselineimmutablefiles/journalprefixesverified;848currenthashfiles;bothcheckpointsexactROrecovery.
Budgets64/16GiBunchanged,473.02GiBfree;600sforecast~6.02/2.60days,not24hguarantee.
Nooriginaldeletion,retentionpolicychange,capitalincrease,AWSspend,promotion.
Finalreportdocs/phase17-readiness.md;Phase18objectives:broaderpreregisteredparent/activity/horizon
cohort,authenticoutcomes/transactionprovenance,100/100certification,24h/7dcapacityandownerretention.
Finaldocumentation/evidencecommitfollows;existinguntrackedrecovery/EBSrecordspreserved.
