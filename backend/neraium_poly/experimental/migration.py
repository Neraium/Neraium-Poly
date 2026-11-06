"""Explicit offline research-code migration; never changes an account ledger."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.experimental.account import _isolated_directory
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from neraium_poly.ops.live_ledger import LiveLedger
from neraium_poly.settings import Settings


def strategy_code_hash():
    return hashlib.sha256(
        b"".join(Path(__file__).with_name(n).read_bytes() for n in ("strategies.py", "intelligence.py"))
    ).hexdigest()


def migrate_research_baseline(config, *, expected_previous_hash, reason, now=None):
    """Require exclusive stopped service, exact previous hash and compatible state.

    Preserve the causal quote history, account balances, orders, risk limits and
    all legacy counters. Archive the old code/checkpoint in one transactional
    coordinator-state record before updating its guard. This is not model or
    certified-strategy approval. At most 32 recorded migrations are supported.
    """
    Settings.from_env()
    if len(reason.strip()) < 20 or len(reason) > 2000:
        raise ValueError("explicit reviewed migration reason required")
    directory = _isolated_directory(config.data_dir, config.certified_directory)
    ledger = LiveLedger(directory)
    try:
        previous = ledger.get("strategy_code_hash")
        current = strategy_code_hash()
        if not previous or previous != expected_previous_hash or previous == current:
            raise ValueError("migration requires exact changed previous code hash")
        checkpoint = ledger.get("strategy_engine")
        if checkpoint is None:
            raise ValueError("existing research checkpoint required")
        engine = ExperimentalStrategyEngine(enabled=config.enabled_strategies, max_tokens=config.max_tokens)
        engine.restore(checkpoint)  # Fail before mutation if state is incompatible.
        migrations = ledger.get("research_baseline_migrations", [])
        if len(migrations) >= 32:
            raise ValueError("research migration record budget exhausted")
        record = {
            "timestamp": (now or datetime.now(UTC)).isoformat(),
            "previous_hash": previous,
            "new_hash": current,
            "reason": reason,
            "previous_checkpoint": checkpoint,
            "checkpoint_preserved": True,
            "certification_authority": False,
            "account_mutation": False,
        }
        ledger.db.execute("BEGIN IMMEDIATE")
        try:
            ledger.put("research_baseline_migrations", [*migrations, record])
            ledger.put("strategy_code_hash", current)
            ledger.db.execute("COMMIT")
        except BaseException:
            ledger.db.execute("ROLLBACK")
            raise
        return {k: v for k, v in record.items() if k != "previous_checkpoint"}
    finally:
        ledger.close()
