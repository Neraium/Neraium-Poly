"""Explicit multi-domain dependencies, persistent evidence and separate claim levels.

No edge is inferred from a keyword. A prior joint relationship and a persistent
change are descriptive research claims, never causality, forecast improvement or
an executable trade. Both review/provenance callbacks deny by default.
"""

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

DOMAINS = {"weather", "crypto", "finance", "economics", "politics", "sports", "esports",
           "technology", "science", "geopolitics", "entertainment", "other"}
KINDS = {"statistical_relationship", "logical_probability_constraint", "causal_hypothesis",
         "forecast_improvement", "executable_opportunity"}
SHA = set("0123456789abcdef")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware relationship timestamps required")
    return at.astimezone(UTC)


def _finite(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite relationship value required")
    if positive and value <= 0:
        raise ValueError("positive relationship bound required")
    return float(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= SHA


def _joint(rows):
    xs, ys = [r[0] for r in rows], [r[1] for r in rows]
    mx, my = mean(xs), mean(ys)
    xx, yy = sum((x-mx)**2 for x in xs), sum((y-my)**2 for y in ys)
    if xx <= 1e-12 or yy <= 1e-12:
        return None
    xy = sum((x-mx)*(y-my) for x,y in zip(xs,ys,strict=True))
    slope = xy/xx
    return {"slope":slope, "intercept":my-slope*mx,
            "correlation":max(-1.0,min(1.0,xy/math.sqrt(xx*yy))),
            "residual_rms":math.sqrt(mean((y-(my-slope*mx+slope*x))**2 for x,y in zip(xs,ys,strict=True)))}


class UniversalRelationships:
    """Bounded joint temporal dependency research across explicitly linked domains.

    Statistical links fit a prior joint OLS/correlation relationship. Persistent
    changes require a changed rolling joint relation AND residual magnitude past
    declared measurement/model uncertainty. This avoids treating isolated price
    excursions as automatically meaningful structural change.
    """

    def __init__(self, *, definition_validator=None, observation_validator=None,
                 warmup=10, persistence=3, persistence_seconds=60, max_links=200):
        if (type(warmup) is not int or not 10 <= warmup <= 100
            or type(persistence) is not int or not 3 <= persistence <= 20
            or not 60 <= persistence_seconds <= 86400
            or type(max_links) is not int or not 1 <= max_links <= 200):
            raise ValueError("bounded conservative relationship configuration required")
        self.definition_validator, self.observation_validator = definition_validator, observation_validator
        self.config = {"warmup":warmup,"persistence":persistence,
                       "persistence_seconds":persistence_seconds,"max_links":max_links}
        self.states, self.rejections = {}, Counter()
        self.evaluations, self.findings = 0, 0

    def _withhold(self, reason):
        key = reason if reason in self.rejections or len(self.rejections) < 64 else "other_bounded_rejection"
        self.rejections[key] += 1
        return {"status":"withheld", "reason":reason, "executable_opportunity":False,
                "causality_verified":False,"forecast_improvement_verified":False,"trading_authority":False}

    def _definition(self, value):
        if not isinstance(value, dict) or len(json.dumps(value,default=str)) > 8192:
            raise ValueError("bounded explicit relationship definition required")
        value = copy.deepcopy(value)
        for key in ("id","left_id","right_id","review_actor"):
            if not isinstance(value.get(key),str) or not 1 <= len(value[key]) <= 256:
                raise ValueError("explicit relationship identity and reviewer required")
        if (value.get("kind") not in KINDS or value.get("left_domain") not in DOMAINS
            or value.get("right_domain") not in DOMAINS or value["left_id"] == value["right_id"]):
            raise ValueError("valid explicit relationship domain and claim type required")
        if self.definition_validator is None or self.definition_validator(value) is not True:
            raise ValueError("independently_reviewed_relationship_definition_required")
        value["available_at"] = _time(value["available_at"]).isoformat()
        if value["kind"] == "statistical_relationship" or value["kind"] == "causal_hypothesis":
            if value.get("relation_type") != "linear_dependency":
                raise ValueError("explicit_supported_joint_relation_required")
            _finite(value.get("minimum_residual"),positive=True)
        elif value["kind"] == "logical_probability_constraint":
            if (value.get("relation_type") not in {"mutually_exclusive", "exhaustive_two_outcomes", "subset"}
                or not _sha(value.get("left_rules_sha256")) or not _sha(value.get("right_rules_sha256"))
                or not value.get("underlying_event_id") or not value.get("settlement_window")
                or value.get("logical_scope_reviewed") is not True):
                raise ValueError("reviewed_logical_payoff_scope_and_rules_required")
            if value["relation_type"] == "exhaustive_two_outcomes" and value.get("outcome_set_complete") is not True:
                raise ValueError("reviewed_complete_exhaustive_set_required")
        return value

    def _observation(self, row, definition, side, now):
        if not isinstance(row,dict):
            raise TypeError("structured_relationship_observation_required")
        if (len(json.dumps(row,default=str))>16384
            or row.get("kind") not in {"market_quote","external_evidence","independent_forecast"}
            or not isinstance(row.get("source"),str) or not 1<=len(row["source"])<=2048
            or (row.get("model_version") is not None
                and (not isinstance(row["model_version"],str) or len(row["model_version"])>256))):
            raise ValueError("bounded_typed_relationship_provenance_required")
        at, available = _time(row["timestamp"]), _time(row["available_at"])
        if (at > available or at > now or available > now or row.get("entity_id") != definition[side+"_id"]
            or row.get("domain") != definition[side+"_domain"] or not _sha(row.get("evidence_sha256"))):
            raise ValueError("causal_identity_matched_relationship_observation_required")
        maximum = definition.get(side+"_max_age_seconds",15 if row.get("kind")=="market_quote" else 3600)
        if not isinstance(maximum,(int,float)) or isinstance(maximum,bool) or not math.isfinite(maximum) or not 0 < maximum <= 86400:
            raise ValueError("bounded_relationship_age_required")
        if row.get("kind") == "market_quote":
            maximum = min(15,maximum)  # Never relax existing executable-book freshness.
        if (now-at).total_seconds() > maximum or (now-available).total_seconds() > maximum:
            raise ValueError("stale_relationship_observation")
        value = _finite(row.get("value"))
        if abs(value)>1e12:
            raise ValueError("relationship_feature_scale_requires_explicit_normalization")
        uncertainty = row.get("uncertainty")
        if not isinstance(uncertainty,dict):
            raise TypeError("explicit_relationship_uncertainty_required")
        error = _finite(uncertainty.get("absolute_error_bound"))
        if not 0 <= error <= 1e12:
            raise ValueError("nonnegative_relationship_uncertainty_required")
        if self.observation_validator is None or self.observation_validator(row) is not True:
            raise ValueError("replayed_relationship_observation_provenance_required")
        return {"value":value,"timestamp":at,"available_at":available,"error":error,
                "evidence_sha256":row["evidence_sha256"],"semantics":row.get("semantics"),
                "model_version":row.get("model_version"),"source":row.get("source")}

    def observe(self, definition, observations, *, now):
        self.evaluations += 1
        try:
            now = _time(now)
            d = self._definition(definition)
            if _time(d["available_at"]) > now:
                return self._withhold("future_relationship_definition")
            if len(observations) != 2:
                return self._withhold("exactly_two_explicitly_linked_observations_required")
            by_id = {o.get("entity_id"):o for o in observations if isinstance(o,dict)}
            if len(by_id)!=2 or set(by_id)!={d["left_id"],d["right_id"]}:
                return self._withhold("ambiguous_relationship_pair")
            left = self._observation(by_id[d["left_id"]],d,"left",now)
            right = self._observation(by_id[d["right_id"]],d,"right",now)
            skew = d.get("max_pair_skew_seconds",15)
            if not isinstance(skew,(int,float)) or isinstance(skew,bool) or not math.isfinite(skew) or not 0 <= skew <= 3600:
                return self._withhold("bounded_relationship_pair_skew_required")
            if abs((left["timestamp"]-right["timestamp"]).total_seconds()) > skew:
                return self._withhold("unaligned_relationship_pair")
            if d["kind"] in {"forecast_improvement","executable_opportunity"}:
                return self._withhold("heldout_forecast_comparison_and_execution_qualification_are_separate")
            logical = self._logical(d,by_id,left,right) if d["kind"] == "logical_probability_constraint" else None
            identity = d["id"]
            if identity not in self.states and len(self.states)>=self.config["max_links"]:
                return self._withhold("relationship_capacity_reached")
            dhash, pairhash = digest(d), digest([left["evidence_sha256"],right["evidence_sha256"]])
            state = self.states.setdefault(identity, {"definition":d,"definition_sha256":dhash,
                "rows":[],"last_at":None,"last_pair":None,"baseline":None,"baseline_evidence":[],"baseline_rows":[],
                "baseline_cutoff":None,"observations":0,
                "candidate_direction":0,"candidate_count":0,"candidate_since":None,"announced":False})
            if state["definition_sha256"] != dhash:
                return self._withhold("relationship_definition_changed_requires_new_version")
            if state["last_at"] and now <= _time(state["last_at"]):
                return self._withhold("non_increasing_relationship_observation_time")
            if state["last_pair"] == pairhash:
                return self._withhold("duplicate_pair_does_not_add_persistence")
            state["last_at"],state["last_pair"] = now.isoformat(),pairhash
            state["observations"] += 1
            row = [left["value"],right["value"],pairhash,now.isoformat(),
                   left["evidence_sha256"],right["evidence_sha256"]]
            state["rows"].append(row)
            state["rows"] = state["rows"][-self.config["warmup"]:]
            if state["observations"] <= self.config["warmup"]:
                if state["observations"] == self.config["warmup"]:
                    state["baseline"] = _joint(state["rows"])
                    state["baseline_evidence"] = [r[2] for r in state["rows"]]
                    state["baseline_rows"] = copy.deepcopy(state["rows"])
                    state["baseline_cutoff"] = now.isoformat()
                return {"status":"warming_up","observations":state["observations"],
                        "required":self.config["warmup"],"executable_opportunity":False}
            if d["kind"] == "logical_probability_constraint":
                direction,magnitude,threshold = logical
                classification = "reviewed_logical_constraint_violation"
                joint = None
            else:
                baseline,joint = state["baseline"],_joint(state["rows"])
                if baseline is None or joint is None:
                    return self._withhold("insufficient_joint_variation_for_relationship_baseline")
                residual = right["value"]-(baseline["intercept"]+baseline["slope"]*left["value"])
                threshold = max(d["minimum_residual"],3*baseline["residual_rms"],
                                right["error"]+abs(baseline["slope"])*left["error"])
                joint_change = (abs(joint["correlation"]-baseline["correlation"]) >= .3
                                or abs(joint["slope"]-baseline["slope"])
                                >= .5*max(abs(baseline["slope"]),1e-9))
                direction = (1 if residual>threshold else -1 if residual < -threshold else 0) if joint_change else 0
                magnitude = abs(residual)
                classification = "persistent_statistical_relationship_change"
            if direction == 0:
                state.update(candidate_direction=0,candidate_count=0,candidate_since=None,announced=False)
            elif direction != state["candidate_direction"]:
                state.update(candidate_direction=direction,candidate_count=1,candidate_since=now.isoformat(),announced=False)
            else:
                state["candidate_count"] += 1
            persistent = (direction!=0 and state["candidate_count"]>=self.config["persistence"]
                          and (now-_time(state["candidate_since"])).total_seconds()>=self.config["persistence_seconds"])
            new = persistent and not state["announced"]
            if new:
                self.findings += 1
                state["announced"] = True
            return {"schema_version":"1.0","engine_version":"universal-joint-relationship-v1",
                    "engine_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "evaluated_at":now.isoformat(),
                    "status":classification if persistent else "observing_joint_relationship",
                    "classification":classification,"finding_new":new,"persistent":persistent,
                    "relationship_id":identity,"definition_sha256":dhash,
                    "domains":[d["left_domain"],d["right_domain"]],"joint_baseline":state["baseline"],
                    "current_joint_relation":joint,"change_magnitude":magnitude,"threshold":threshold,
                    "persistence_count":state["candidate_count"],"persistence_since":state["candidate_since"],
                    "evidence_sha256":[left["evidence_sha256"],right["evidence_sha256"]],
                    "baseline_evidence_sha256":state["baseline_evidence"],"baseline_cutoff":state["baseline_cutoff"],
                    "baseline_source_evidence_sha256":[r[4:6] for r in state["baseline_rows"]],
                    "current_window_evidence_sha256":[r[2] for r in state["rows"]],
                    "model_versions":[left["model_version"],right["model_version"]],
                    "uncertainty":"Declared source/model error bounds; no significance or iid guarantee",
                    "statistical_significance":None,"causality_verified":False,
                    "forecast_improvement_verified":False,"executable_opportunity":False,
                    "execution_blocker":"fees/slippage/depth/rules/timing/risk/authorization and atomic execution require separate qualification",
                    "trading_authority":False,"certification_authority":False}
        except Exception as error:  # noqa: BLE001 - verifier failures never qualify a relationship
            return self._withhold(str(error)[:140])

    def _logical(self, d, original, left, right):
        for side,obs in (("left",left),("right",right)):
            raw=original[d[side+"_id"]]
            if (obs["semantics"]!="binary_event_probability" or not 0<=obs["value"]<=1
                or raw.get("rules_sha256")!=d[side+"_rules_sha256"]
                or raw.get("underlying_event_id")!=d["underlying_event_id"]
                or raw.get("settlement_window")!=d["settlement_window"]):
                raise ValueError("logical_event_semantics_rule_or_timing_mismatch")
        a,b=left["value"],right["value"]
        threshold=max(1e-10,left["error"]+right["error"])
        if d["relation_type"]=="mutually_exclusive":
            delta=a+b-1
        elif d["relation_type"]=="exhaustive_two_outcomes":
            delta=abs(a+b-1)
        else:
            delta=a-b  # Explicit reviewed left-subset/right-superset relation.
        return (1 if delta>threshold else 0),max(0,delta),threshold

    def checkpoint(self):
        return copy.deepcopy({"schema_version":"1.0","config":self.config,"states":self.states,
                              "evaluations":self.evaluations,"findings":self.findings,
                              "rejections":dict(self.rejections)})

    def restore(self, value):
        if (not isinstance(value,dict) or value.get("schema_version")!="1.0" or value.get("config")!=self.config
            or not isinstance(value.get("states"),dict) or len(value["states"])>self.config["max_links"]):
            raise ValueError("relationship checkpoint schema/config/capacity mismatch")
        if len(json.dumps(value,allow_nan=False))>32*1024**2:
            raise ValueError("relationship checkpoint byte budget")
        for identity,state in value["states"].items():
            d=self._definition(state["definition"])
            if identity!=d["id"] or digest(d)!=state["definition_sha256"] or not _sha(state["last_pair"]):
                raise ValueError("relationship checkpoint definition integrity")
            if type(state["observations"]) is not int or state["observations"]<1:
                raise ValueError("relationship checkpoint counter")
            if len(state["rows"])>self.config["warmup"] or not state["rows"]:
                raise ValueError("relationship checkpoint window budget")
            latest=_time(state["last_at"])
            if (not isinstance(state.get("baseline_evidence"),list)
                or len(state["baseline_evidence"])>self.config["warmup"]
                or any(not _sha(h) for h in state["baseline_evidence"])):
                raise ValueError("relationship baseline provenance required")
            if state["observations"]>=self.config["warmup"] and (
                len(state["baseline_evidence"])!=self.config["warmup"]
                or not state.get("baseline_cutoff") or _time(state["baseline_cutoff"])>latest):
                raise ValueError("relationship causal baseline cutoff required")
            if len(state.get("baseline_rows",[]))!=len(state["baseline_evidence"]):
                raise ValueError("relationship frozen baseline row provenance required")
            if [r[2] for r in state["baseline_rows"]]!=state["baseline_evidence"]:
                raise ValueError("relationship frozen baseline evidence mismatch")
            for row in state["rows"]+state["baseline_rows"]:
                if len(row)!=6 or not all(_sha(row[i]) for i in (2,4,5)) or _time(row[3])>latest:
                    raise ValueError("relationship checkpoint row integrity")
                if any(abs(_finite(row[i]))>1e12 for i in (0,1)) or digest(row[4:6])!=row[2]:
                    raise ValueError("relationship row scale or evidence pair mismatch")
            if (type(state["candidate_count"]) is not int or state["candidate_count"]<0
                or type(state["candidate_direction"]) is not int or state["candidate_direction"] not in {-1,0,1}
                or type(state["announced"]) is not bool):
                raise ValueError("relationship checkpoint persistence")
            if state["candidate_since"] and _time(state["candidate_since"])>latest:
                raise ValueError("relationship checkpoint future persistence")
            if state["baseline"] is not None:
                for number in state["baseline"].values():
                    _finite(number)
        for key in ("evaluations","findings"):
            if type(value.get(key)) is not int or value[key]<0:
                raise ValueError("relationship checkpoint totals")
        if not isinstance(value.get("rejections"),dict) or len(value["rejections"])>65:
            raise ValueError("relationship checkpoint rejection budget")
        if any(type(n) is not int or n<0 for n in value["rejections"].values()):
            raise ValueError("relationship checkpoint rejection counts")
        self.states=copy.deepcopy(value["states"])
        self.evaluations,self.findings=value["evaluations"],value["findings"]
        self.rejections=Counter(value["rejections"])

    def summary(self):
        return {"registered_relationships":len(self.states),"evaluations":self.evaluations,
                "persistent_findings":self.findings,"rejections":dict(self.rejections),
                "graph":[{"id":key,"left":s["definition"]["left_id"],"right":s["definition"]["right_id"],
                          "domains":[s["definition"]["left_domain"],s["definition"]["right_domain"]],
                          "claim_type":s["definition"]["kind"],"definition_sha256":s["definition_sha256"]}
                         for key,s in self.states.items()],
                "causality_verified":False,"forecast_improvement_verified":False,
                "executable_opportunities":0,"certification_authority":False,"trading_authority":False}
