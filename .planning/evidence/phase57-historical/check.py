"""Focused checks for causal arrivals, depth debit, and poll aliasing."""
from replay import polls, replay

META = {"native":{"mos":5,"fd":{"r":0}},"rows":[{"token_id":"a"},{"token_id":"b"}]}


def quote(t, ask, bid):
    return dict(asks={ask:5},bids={bid:5},receipt=t,exchange=t,id=str(t))


def pair(t, b_ask):
    return {"a":quote(t,.4,.38),"b":quote(t,b_ask,.39)}


frames=[(0,pair(0,.65)),(.1,pair(.1,.4)),(.61,pair(.61,.4)),
        (1.12,pair(1.12,.65)),(1.63,pair(1.63,.65)),(5,pair(5,.65))]
stats, episodes, attempts = replay(frames, {"m":META},max_gap=5)
assert stats["m"]["after_fee_episodes"] == 1 and len(episodes[0]["quotes"]) == 1
assert abs(episodes[0]["max_conversion_usd"]-1)<1e-8
assert abs(episodes[0]["observed_duration_s"]-.51)<1e-8
assert stats["m"]["partial_baskets"] == 1 and attempts[0]["arrival_times"] == [.61,1.12,1.63]
assert attempts[0]["arrival_fills"][1]["quantity"] == 0
assert abs(attempts[0]["net"]+.10)<1e-8 and attempts[0]["unwinds"][0]["quantity"] == 5
assert replay(list(polls(frames,0)),{"m":META},max_gap=5)[1] == []
# An unchanged displayed ask cannot replace liquidity used on the first attempt.
same=[(0,pair(0,.4)),(.6,pair(.6,.4)),(1.2,pair(1.2,.4)),(1.8,pair(1.8,.4)),
      (2.4,{"b":quote(2.4,.4,.39)}),(3,pair(3,.4)),(3.6,pair(3.6,.4)),
      (4.2,pair(4.2,.4)),(4.8,pair(4.8,.4))]
_,_,attempts = replay(same,{"m":META},max_gap=5)
assert len(attempts)==2 and attempts[0]["complete"]
assert all(leg["quantity"]==0 for leg in attempts[1]["legs"])
print("Latency, partial unwind, repeated liquidity and missed-poll checks passed.")
