"""Persistent changes in model/market relationships, never trade authorization."""

from datetime import datetime
from math import isfinite

from neraium_poly.research.phase13.contracts import SportsMapping, SportsPrediction


class SportsRelationshipResearch:
    """Causal, bounded temporal relationship baselines with evidence persistence.

    This engine studies changes in the relationship between independently
    estimated team-strength probability and observed market probability. A
    residual, a persistent relationship shift and an executable edge are different
    claims. Only the descriptive relationship claim is supported here.
    """

    def __init__(self, *, warmup=10, persistence=3, persistence_seconds=60, threshold=0.08, max_events=200):
        if (
            type(warmup) is not int or not 10 <= warmup <= 100
            or type(persistence) is not int or not 3 <= persistence <= 20
            or not 60 <= persistence_seconds <= 86400
            or not 0.05 <= threshold <= 0.5
            or type(max_events) is not int or not 1 <= max_events <= 200
        ):
            raise ValueError("bounded conservative relationship configuration required")
        self.config = {"warmup": warmup, "persistence": persistence, "persistence_seconds": persistence_seconds,
                       "threshold": threshold, "max_events": max_events}
        self.states = {}
        self.evaluations = 0
        self.findings = 0

    def observe(
        self, mapping, prediction, *, market_probability, market_timestamp, market_available_at,
        evidence_sha256, now,
    ):
        mapping = SportsMapping.model_validate(mapping.model_dump() if isinstance(mapping, SportsMapping) else mapping)
        prediction = SportsPrediction.model_validate(
            prediction.model_dump() if isinstance(prediction, SportsPrediction) else prediction
        )
        if (
            any(t.tzinfo is None for t in (now, market_timestamp, market_available_at))
            or not isinstance(market_probability, (int, float)) or isinstance(market_probability, bool)
            or not isfinite(market_probability) or not 0 <= market_probability <= 1
            or len(evidence_sha256) != 64 or any(c not in "0123456789abcdef" for c in evidence_sha256)
        ):
            raise ValueError("valid causal relationship observation required")
        if (
            prediction.game_id != mapping.game_id or prediction.selected_team_id != mapping.selected_team_id
            or prediction.cutoff > now or (now - prediction.cutoff).total_seconds() > 3600
            or market_timestamp > now or market_available_at > now
            or (now - market_timestamp).total_seconds() > 15
            or (now - market_available_at).total_seconds() > 15 or mapping.event_start <= now
        ):
            return {"status": "withheld", "reason": "fresh_causal_pre_event_model_market_pair_required",
                    "executable_opportunity": False}
        comparison = "team_win_probability_minus_market_binary_probability"
        model_value = prediction.probability
        if prediction.uncertainty.get("fractional_tie_contract_market_comparison_supported") is False:
            outcomes = prediction.uncertainty.get("outcome_probabilities", {})
            if (
                set(outcomes) != {"win", "tie", "loss"}
                or any(not isinstance(x, (int, float)) or not isfinite(x) or not 0 <= x <= 1
                       for x in outcomes.values())
                or abs(sum(outcomes.values()) - 1) > 1e-12
                or abs(outcomes["win"] - prediction.probability) > 1e-12
            ):
                return {"status": "withheld", "reason": "qualified_ternary_prediction_required",
                        "executable_opportunity": False}
            model_value = outcomes["win"] + 0.5 * outcomes["tie"]
            comparison = "expected_fractional_payout_minus_market_quote; not win_probability_comparison"
        key = f"{mapping.event_id}|{mapping.market_id}|{mapping.token_id}|{prediction.model_sha256}"
        if key not in self.states and len(self.states) >= self.config["max_events"]:
            return {"status": "withheld", "reason": "relationship_capacity_reached", "executable_opportunity": False}
        state = self.states.setdefault(key, {
            "event_id": mapping.event_id, "game_id": mapping.game_id, "market_id": mapping.market_id,
            "rules_sha256": mapping.rules_sha256, "model_sha256": prediction.model_sha256,
            "observations": 0, "baseline": 0.0, "last_at": None, "last_evidence": None,
            "candidate_direction": 0, "candidate_count": 0, "candidate_since": None,
            "candidate_announced": False,
        })
        if state["rules_sha256"] != mapping.rules_sha256 or state["game_id"] != mapping.game_id:
            return {"status": "withheld", "reason": "relationship_identity_or_rule_changed", "executable_opportunity": False}
        if state["last_at"] is not None and now <= datetime.fromisoformat(state["last_at"]):
            return {"status": "withheld", "reason": "non_increasing_observation_time", "executable_opportunity": False}
        if state["last_evidence"] == evidence_sha256:
            return {"status": "withheld", "reason": "duplicate_evidence_does_not_add_persistence",
                    "executable_opportunity": False}
        residual = model_value - market_probability
        self.evaluations += 1
        state["observations"] += 1
        state["last_at"], state["last_evidence"] = now.isoformat(), evidence_sha256
        if state["observations"] <= self.config["warmup"]:
            state["baseline"] += (residual - state["baseline"]) / state["observations"]
            return {"status": "warming_up", "observations": state["observations"],
                    "required": self.config["warmup"], "executable_opportunity": False}
        shift = residual - state["baseline"]
        direction = 1 if shift >= self.config["threshold"] else -1 if shift <= -self.config["threshold"] else 0
        if direction == 0:
            state["candidate_direction"], state["candidate_count"], state["candidate_since"] = 0, 0, None
            state["candidate_announced"] = False
            # Update ordinary temporal baseline only after classifying this point;
            # no future observations enter the current relationship finding.
            state["baseline"] = 0.95 * state["baseline"] + 0.05 * residual
        elif direction != state["candidate_direction"]:
            state["candidate_direction"], state["candidate_count"], state["candidate_since"] = direction, 1, now.isoformat()
            state["candidate_announced"] = False
        else:
            state["candidate_count"] += 1
        persistent = (
            direction != 0 and state["candidate_count"] >= self.config["persistence"]
            and (now - datetime.fromisoformat(state["candidate_since"])).total_seconds()
            >= self.config["persistence_seconds"]
        )
        new_finding = persistent and not state["candidate_announced"]
        if new_finding:
            self.findings += 1
            state["candidate_announced"] = True
        return {
            "status": "persistent_descriptive_relationship_change" if persistent else "observing",
            "classification": "statistical_relationship", "comparison": comparison, "event_id": mapping.event_id,
            "model_market_residual": residual, "prior_temporal_baseline": state["baseline"],
            "relationship_shift": shift, "persistence_count": state["candidate_count"],
            "new_relationship_finding": new_finding,
            "persistence_since": state["candidate_since"], "evidence_sha256": evidence_sha256,
            "model_sha256": prediction.model_sha256, "rules_sha256": mapping.rules_sha256,
            "uncertainty": "Uncalibrated model; no causal influence or profitability established",
            "causal_hypothesis_verified": False, "logical_constraint_verified": False,
            "executable_opportunity": False, "trading_authority": False,
        }

    def checkpoint(self):
        return {"schema_version": "1.0", "config": self.config, "states": self.states,
                "evaluations": self.evaluations, "findings": self.findings}

    def restore(self, data):
        if data.get("schema_version") != "1.0" or data.get("config") != self.config:
            raise ValueError("relationship checkpoint version/config mismatch")
        states = data.get("states")
        if not isinstance(states, dict) or len(states) > self.config["max_events"]:
            raise ValueError("invalid relationship checkpoint capacity")
        for state in states.values():
            if (
                type(state.get("observations")) is not int or state["observations"] < 0
                or not isinstance(state.get("baseline"), (float, int)) or not isfinite(state["baseline"])
                or not -1 <= state["baseline"] <= 1
                or type(state.get("candidate_count")) is not int or state["candidate_count"] < 0
                or type(state.get("candidate_direction")) is not int
                or state["candidate_direction"] not in {-1, 0, 1}
                or type(state.get("candidate_announced")) is not bool
                or state.get("last_at") is None or datetime.fromisoformat(state["last_at"]).tzinfo is None
            ):
                raise ValueError("invalid relationship checkpoint state")
            if state["candidate_count"]:
                since = state.get("candidate_since")
                if (
                    not isinstance(since, str) or datetime.fromisoformat(since).tzinfo is None
                    or datetime.fromisoformat(since) > datetime.fromisoformat(state["last_at"])
                    or state["candidate_direction"] == 0
                ):
                    raise ValueError("invalid relationship persistence checkpoint")
            elif state.get("candidate_since") is not None or state["candidate_direction"] != 0:
                raise ValueError("invalid empty relationship persistence checkpoint")
        for name in ("evaluations", "findings"):
            if type(data.get(name)) is not int or data[name] < 0:
                raise ValueError("invalid relationship checkpoint counters")
        import copy
        self.states = copy.deepcopy(states)
        self.evaluations, self.findings = data["evaluations"], data["findings"]
