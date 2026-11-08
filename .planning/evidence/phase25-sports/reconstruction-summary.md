# Exploratory current-vintage NHL reconstruction
Frozen before scoring: last60of197 unique publisher-finalgames,137earliergames initially; expanding chronological training with24-hour start-time embargo and unchanged100games/5perparticipant gates. All60targets eligible. Fourfixedalgorithms, samecohort,1000seed20261108 UTCcalendar-dayblockbootstrap draws,9blocks,oneCPUworker. No optimization, historicalmarketprices, executionbooks, ledger writes, settlements or P/L.

| Model | Brier | Log loss |
|---|---:|---:|
| NHL Elo | .242667 | .678195 |
| NHL Beta-frequency | .245088 | .691212 |
| Half-probability baseline | .250000 | .693147 |
| Causal home-frequency baseline | .250471 | .694132 |

Elo minushalf Brier difference−.007333; descriptive95%dayblock interval[−.024305,+.008776]. Betaminushalf−.004912,interval[−.029431,+.026393]. Every candidate-versus-baseline Brier/loglossinterval includeszero. No statisticallycredible superiorforecastingestablished, no claimafter-costadvantage. These unadjusted exploratoryintervals cannot establish significance or modelpromotion.

This is CURRENT-VINTAGE EXPLORATORY RECONSTRUCTION, not prospective evidence, verifiedhistoricalpoint-in-time data, untouchedholdout, certification or officialsettlement. Models were already developed usingthisdataset. All source data firstretrievednow; precisehistoricalresultavailability is unknown.24-hour embargo reducesordinaryoverlapbutcannotproveoldfinality/postponement/revision handling. Sharedteamdependence acrossdays remains; effectiveindependentcountnull. Calibration-in-large is descriptiveonly. All60targets/predictions,includingerrors,preserved inresults.

Rawsource data/phase25/nhl-evidence.json retained in thisworker;sourceSHA256 ca5116acfc69b43c7e9375094358a35435ba305684f683fbfef147d9bd1750da;parsed197-gamedatasetSHA256 b64fe8acafdb989e65d549ad461b6718d7a5dbcf11e609017d7d2cc163faf86b;scriptSHA256 9cb61b134b2359b33e26f3d0f1221e5f775e7c6e2d187d3bf483ff3a70e9e94e. Script is copied byte-identically as nhl-reconstruction.py. To reproduce without overwriting immutableexperimentartifacts, use afreshdisposableworkingdirectory containingthe referencedrawfile under data/phase25 and anempty .planning/evidence/phase25-sports; execute thescript with sourcecodePYTHONPATHfromthe9d07c07worktree. Existingprotocol refusesoverwrite. The two genuineisolatedprospectiveforecasts remainuntouched andseparate.
