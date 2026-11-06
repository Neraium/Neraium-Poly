"""Observed bid-depth horizon exits, atomically recorded with experimental capital.

Only long inventory can be sold. This is a taker simulation, not a queue model.
"""

import hashlib
import json
from datetime import timedelta

from neraium_poly.data import assess_book
from neraium_poly.risk import RiskViolation

EPS = 1e-8


class HorizonExits:
    def __init__(self, risk, config):
        self.risk, self.config = risk, config
        risk.db.executescript("""
        CREATE TABLE IF NOT EXISTS experimental_exits (
          id TEXT PRIMARY KEY, token TEXT NOT NULL, strategy TEXT NOT NULL,
          submitted TEXT NOT NULL, ready TEXT NOT NULL, expires TEXT NOT NULL,
          requested REAL NOT NULL, filled REAL NOT NULL DEFAULT 0,
          proceeds REAL NOT NULL DEFAULT 0, fees REAL NOT NULL DEFAULT 0,
          pnl REAL NOT NULL DEFAULT 0, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS experimental_exit_books(book TEXT PRIMARY KEY,digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS experimental_exit_watermarks(token TEXT PRIMARY KEY,timestamp TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS experimental_exit_depth (
          book TEXT NOT NULL, price REAL NOT NULL, used REAL NOT NULL,
          PRIMARY KEY(book,price));
        """)

    def request(self, token, strategy, now):
        key = hashlib.sha256(f"experimental-exit:{token}:{strategy}:{now.isoformat()}".encode()).hexdigest()
        with self.risk._transaction():
            old = self.risk.db.execute(
                "SELECT id FROM experimental_exits WHERE token=? AND status IN ('open','partial')", (token,)
            ).fetchone()
            if old:
                return old[0]
            position = self.risk.db.execute(
                "SELECT quantity FROM positions WHERE token=?", (token,)
            ).fetchone()
            if position is None:
                return None
            metadata = self.risk.db.execute(
                "SELECT market FROM experimental_inputs WHERE json_extract(market,'$.token_id')=? ORDER BY rowid DESC LIMIT 1",
                (token,),
            ).fetchone()
            if metadata is None or position[0] < json.loads(metadata[0])["min_order_size"] - EPS:
                return None
            self.risk.db.execute(
                "INSERT INTO experimental_exits(id,token,strategy,submitted,ready,expires,requested,status) "
                "VALUES(?,?,?,?,?,?,?,'open')",
                (
                    key,
                    token,
                    strategy,
                    now.isoformat(),
                    (now + timedelta(milliseconds=self.config.latency_ms)).isoformat(),
                    (now + timedelta(seconds=30)).isoformat(),
                    position[0],
                ),
            )
            self.risk._audit(
                "experimental_exit_requested", {"id": key, "token": token, "strategy": strategy}, now
            )
        return key

    def process(self, exit_id, book, now, fee_rate, slippage_per_share, fee_evidence=None):
        from datetime import datetime

        if fee_rate is None or not 0 <= fee_rate <= 1:
            return {"status": "withheld", "reasons": ["unknown_exit_fees"], "id": exit_id}
        with self.risk._transaction():
            row = self.risk.db.execute("SELECT * FROM experimental_exits WHERE id=?", (exit_id,)).fetchone()
            if row is None:
                raise KeyError(exit_id)
            if row["status"] not in {"open", "partial"}:
                return dict(row)
            state = self.risk._state(now)
            if (
                state["kill_switch"]
                or state["daily_pnl"]
                <= -self.risk.limits.bankroll * self.risk.limits.daily_loss_fraction + EPS
                or state["drawdown"] >= state["peak"] * self.risk.limits.drawdown_fraction - EPS
            ):
                return {"status": "withheld", "reasons": ["kill_switch_or_loss_limit"], "id": exit_id}
            if now >= datetime.fromisoformat(row["expires"]):
                self.risk.db.execute("UPDATE experimental_exits SET status='expired' WHERE id=?", (exit_id,))
                self.risk._audit("experimental_exit_expired", {"id": exit_id}, now)
                return dict(
                    self.risk.db.execute("SELECT * FROM experimental_exits WHERE id=?", (exit_id,)).fetchone()
                )
            if now < datetime.fromisoformat(row["ready"]):
                return dict(row)
            position = self.risk.db.execute(
                "SELECT * FROM positions WHERE token=?", (row["token"],)
            ).fetchone()
            if position is None:
                self.risk.db.execute(
                    "UPDATE experimental_exits SET status='cancelled' WHERE id=?", (exit_id,)
                )
                return {"id": exit_id, "status": "cancelled", "reason": "no_long_inventory"}
            health = assess_book(
                book,
                now,
                max_age_seconds=self.risk.limits.max_book_age_seconds,
                max_spread=self.risk.limits.max_spread,
                expected_token=row["token"],
            )
            if (
                not health.healthy
                or book.source
                not in {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
                or book.exchange != "polymarket"
                or book.market_id != position["market"]
                or book.available_at < datetime.fromisoformat(row["ready"])
                or book.timestamp < datetime.fromisoformat(row["ready"])
            ):
                return {
                    "id": exit_id,
                    "status": "withheld",
                    "reasons": list(health.reasons) or ["post_latency_observation_required"],
                }
            if len({p.price for p in book.bids}) != len(book.bids):
                raise RiskViolation("duplicate exit depth levels")
            # A repeated receipt of the same source-time depth is not replenished liquidity.
            key = hashlib.sha256(
                json.dumps(
                    [book.exchange, book.token_id, book.timestamp.isoformat()], separators=(",", ":")
                ).encode()
            ).hexdigest()
            digest = hashlib.sha256(
                json.dumps(
                    [[(p.price, p.size) for p in book.bids], [(p.price, p.size) for p in book.asks]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            known = self.risk.db.execute(
                "SELECT digest FROM experimental_exit_books WHERE book=?", (key,)
            ).fetchone()
            watermark = self.risk.db.execute(
                "SELECT timestamp FROM experimental_exit_watermarks WHERE token=?", (book.token_id,)
            ).fetchone()
            if (known and known[0] != digest) or (
                watermark and book.timestamp < datetime.fromisoformat(watermark[0])
            ):
                return {
                    "id": exit_id,
                    "status": "withheld",
                    "reasons": ["conflicting_or_regressing_exit_book"],
                }
            self.risk.db.execute("INSERT OR IGNORE INTO experimental_exit_books VALUES(?,?)", (key, digest))
            self.risk.db.execute(
                "INSERT INTO experimental_exit_watermarks VALUES(?,?) ON CONFLICT(token) DO UPDATE SET timestamp=excluded.timestamp",
                (book.token_id, book.timestamp.isoformat()),
            )
            floor = max(0, book.bids[0].price - slippage_per_share)
            needed = min(position["quantity"], row["requested"] - row["filled"])
            qty = proceeds = 0.0
            for level in book.bids:
                if level.price < floor - EPS:
                    break
                prior = self.risk.db.execute(
                    "SELECT used FROM experimental_exit_depth WHERE book=? AND price=?", (key, level.price)
                ).fetchone()
                available = max(0, level.size * self.config.participation_rate - (prior[0] if prior else 0))
                take = min(needed - qty, available)
                if take > EPS:
                    qty += take
                    proceeds += take * level.price
                    self.risk.db.execute(
                        "INSERT INTO experimental_exit_depth VALUES(?,?,?) ON CONFLICT(book,price) "
                        "DO UPDATE SET used=used+excluded.used",
                        (key, level.price, take),
                    )
                if qty >= needed - EPS:
                    break
            if qty <= EPS:
                return dict(row)
            fees = proceeds * fee_rate
            fraction = qty / position["quantity"]
            basis = (position["principal"] + position["fees"]) * fraction
            pnl = proceeds - fees - basis
            remaining = position["quantity"] - qty
            if remaining <= EPS:
                self.risk.db.execute("DELETE FROM positions WHERE token=?", (row["token"],))
            else:
                self.risk.db.execute(
                    "UPDATE positions SET quantity=?,principal=principal*?,fees=fees*?,mark=? WHERE token=?",
                    (remaining, 1 - fraction, 1 - fraction, book.bids[0].price, row["token"]),
                )
            self.risk.db.execute(
                "UPDATE account SET cash=cash+?,realized=realized+? WHERE id=1", (proceeds - fees, pnl)
            )
            self.risk.db.execute(
                "INSERT INTO daily(day,pnl) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET pnl=pnl+?",
                (now.date().isoformat(), pnl, pnl),
            )
            status = (
                "filled" if row["filled"] + qty >= row["requested"] - EPS or remaining <= EPS else "partial"
            )
            self.risk.db.execute(
                "UPDATE experimental_exits SET filled=filled+?,proceeds=proceeds+?,fees=fees+?,pnl=pnl+?,status=? WHERE id=?",
                (qty, proceeds, fees, pnl, status, exit_id),
            )
            equity = self.risk._state(now)["equity"]
            self.risk.db.execute("UPDATE account SET peak=MAX(peak,?) WHERE id=1", (equity,))
            self.risk._audit(
                "experimental_exit_fill",
                {
                    "id": exit_id,
                    "strategy_id": row["strategy"],
                    "token": row["token"],
                    "quantity": qty,
                    "proceeds": proceeds,
                    "fees": fees,
                    "pnl": pnl,
                    "book_id": book.id,
                    "fee_evidence": fee_evidence,
                    "source_at": book.timestamp.isoformat(),
                    "available_at": book.available_at.isoformat(),
                    "assumption": "post-latency displayed bids, bounded participation",
                },
                now,
            )
            return dict(
                self.risk.db.execute("SELECT * FROM experimental_exits WHERE id=?", (exit_id,)).fetchone()
            )

    def expire(self, now):
        from datetime import datetime

        with self.risk._transaction():
            for row in self.risk.db.execute(
                "SELECT id,expires FROM experimental_exits WHERE status IN ('open','partial')"
            ).fetchall():
                if datetime.fromisoformat(row["expires"]) <= now:
                    self.risk.db.execute(
                        "UPDATE experimental_exits SET status='expired' WHERE id=?", (row["id"],)
                    )
                    self.risk._audit("experimental_exit_expired", {"id": row["id"]}, now)

    def pending(self):
        return [
            dict(r)
            for r in self.risk.db.execute(
                "SELECT * FROM experimental_exits WHERE status IN ('open','partial')"
            )
        ]
