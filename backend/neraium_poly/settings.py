"""Fail closed even when an operator changes the live feature flags."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    paper_trading: bool = True
    live_trading_enabled: bool = False

    def __post_init__(self):
        if not self.paper_trading or self.live_trading_enabled:
            raise ValueError("Only paper execution is implemented and authorized")

    @classmethod
    def from_env(cls):
        return cls(
            paper_trading=os.getenv("PAPER_TRADING", "true").lower() == "true",
            live_trading_enabled=os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false",
        )
