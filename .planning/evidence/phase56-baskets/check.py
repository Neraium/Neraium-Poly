from scan import Depth, admitted, attempt, compatible_rules, payout_floor, size_search

assert admitted([{"receipt": 10, "exchange": 10}, {"receipt": 11, "exchange": 11}], 12)
assert not admitted([{"receipt": 10, "exchange": 10}, {"receipt": 11, "exchange": -4}], 12)
m = {
    "a": {"rows": [{"resolution_rules": "noon", "resolution_source": "binance", "end_time": "18"}]},
    "b": {"rows": [{"resolution_rules": "noon", "resolution_source": "binance", "end_time": "19"}]},
}
assert not compatible_rules(m, ["a", "b"])
assert payout_floor([[1, 0], [0, 1], [0.5, 0.5]]) == 1
assert payout_floor([[0, 1], [1, 1], [1, 0], [0, 0]]) == 0
assert (
    size_search([{0.4: 2}, {0.4: 10}], [0.07, 0.07], 5, buy=True, floor=1, cash=500, conversion=0.1) is None
)
d = Depth()
d.observe(("a", True), {0.4: 5})
assert d.execute(("a", True), 4, 0.07, buy=True, limit=0.4)["quantity"] == 4
d.observe(("a", True), {0.4: 5})
assert d.execute(("a", True), 4, 0.07, buy=True, limit=0.4)["quantity"] == 1
decision = {"quantity": 5, "legs": [{"limit": 0.4}, {"limit": 0.4}]}
result = attempt(Depth(), ["a", "b"], [0.07, 0.07], decision, [{0.4: 5}, None, {0.35: 5}, None], True, 0.1)
assert not result["complete"] and result["net"] < 0 and result["residual_shares"] == [0, 0]
print("Stale pair, mismatched rules, payout exception, depth, liquidity reuse and failed-leg unwind passed.")

best = size_search(
    [{0.35: 6, 0.6: 9}, {0.35: 6, 0.6: 9}], [0, 0], 5, buy=True, floor=1, cash=500, conversion=0
)
assert best["quantity"] == 6 and best["largest_profitable_shares"] == 14.99
