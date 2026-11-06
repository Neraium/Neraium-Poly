"""Extensible domain model registry; registration is research capability only."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainModelAdapter:
    domain: str
    model_version: str
    supported_contract_types: tuple[str, ...]
    input_requirements: tuple[str, ...]
    feature_version: str
    implementation: Callable
    authorization: str = "research_only"

    def forecast(self, contract, evidence, *, cutoff):
        if contract.domain != self.domain or contract.contract_type not in self.supported_contract_types:
            return {
                "status": "withheld",
                "probability": None,
                "reasons": ["unsupported_domain_model_contract"],
            }
        return self.implementation(contract, evidence, cutoff=cutoff)


class DomainModelRegistry:
    def __init__(self):
        self.models = {}

    def register(self, model):
        if not isinstance(model, DomainModelAdapter) or model.authorization != "research_only":
            raise ValueError("only explicit research domain model capabilities may register")
        if model.domain in self.models or not model.supported_contract_types or not model.input_requirements:
            raise ValueError("unique domain model and explicit input requirements required")
        self.models[model.domain] = model

    def status(self):
        return {
            d: {
                "model_version": m.model_version,
                "feature_version": m.feature_version,
                "supported_contract_types": list(m.supported_contract_types),
                "input_requirements": list(m.input_requirements),
                "authorization": "research_only",
                "trading_authority": False,
            }
            for d, m in self.models.items()
        }


def research_registry():
    from neraium_poly.research.phase14.economics import forecast_economic
    from neraium_poly.research.phase14.finance import FEATURE_VERSION, MODEL_VERSION, forecast_financial
    from neraium_poly.research.phase14.weather import MODEL_VERSION as WEATHER_VERSION
    from neraium_poly.research.phase14.weather import forecast_weather

    r = DomainModelRegistry()
    r.register(
        DomainModelAdapter(
            "crypto",
            MODEL_VERSION,
            ("binance_minute_terminal_close_above",),
            (
                "exact reviewed candle-time convention",
                "720+ completed causal contiguous reference candles",
                "held-out calibration missing",
            ),
            FEATURE_VERSION,
            forecast_financial,
        )
    )
    r.register(
        DomainModelAdapter(
            "weather",
            WEATHER_VERSION,
            ("metar_daily_high_celsius_bin",),
            (
                "exact station/units/local observation window",
                "qualified calibrated predictive distribution unavailable",
            ),
            "exact-metAR-station-variable-window-v1",
            forecast_weather,
        )
    )
    r.register(
        DomainModelAdapter(
            "economics",
            "official-economic-context-only-v1",
            ("fomc_target_upper_bound_change",),
            (
                "exact first-release vintage",
                "verified publication availability",
                "qualified probability model unavailable",
            ),
            "release-vintage-qualification-v1",
            forecast_economic,
        )
    )
    return r
