"""Synthetic queue and cancellation boundary checks, excluded from the scorecard."""

from replay import consume, take

order = {"effective": 1.0, "expires": 10.0, "cancel_effective": 5.5, "price": 0.4, "ahead": 8.0, "left": 5.0}
assert consume(order, 0.9, 0.4, 100) == 0
assert consume(order, 2, 0.401, 100) == 0
assert consume(order, 2, 0.4, 6) == 0
assert order["ahead"] == 2
assert consume(order, 5.25, 0.4, 4) == 2
assert consume(order, 5.5, 0.4, 20) == 0
assert order["left"] == 3
q, value, fees, levels = take({0.4: 1, 0.3: 2}, 5)
assert q == 3 and abs(value - 1) < 1e-9 and fees > 0 and len(levels) == 2
print("Queue priority, partial fill, cancellation race, depth and fees passed.")
