"""Tests for v1.0.3 noise ordering (core.noisy_order)."""
import random
import image_grid_core as core

vals = [i / 19 for i in range(20)]            # 20 distinct brightness values
shuf = vals[:]; random.Random(1).shuffle(shuf)

print("=== permutation validity, all modes ===")
for mode in ("wave", "field", "jitter"):
    o = core.noisy_order(vals, mode, freq=2, amp=1.0, seed=7)
    assert sorted(o) == list(range(20)), (mode, o)
print("  ok")

print("=== amp=0 -> pure monotonic sort (wave & field) ===")
for mode in ("wave", "field"):
    o = core.noisy_order(shuf, mode, freq=3, amp=0.0)
    assert [shuf[i] for i in o] == sorted(shuf), mode
print("  ok")

print("=== wave freq controls number of oscillations ===")
def turns(seq):
    return sum(1 for k in range(1, len(seq) - 1)
               if (seq[k] - seq[k - 1]) * (seq[k + 1] - seq[k]) < 0)
t2 = turns([vals[i] for i in core.noisy_order(vals, "wave", freq=2, amp=1.0)])
t5 = turns([vals[i] for i in core.noisy_order(vals, "wave", freq=5, amp=1.0)])
assert t5 > t2, (t2, t5)
print("  freq2 turns=%d  freq5 turns=%d" % (t2, t5))

print("=== wave arrangement is independent of incoming order ===")
a = [round(vals[i], 4) for i in core.noisy_order(vals, "wave", freq=3, amp=1.0)]
b = [round(shuf[i], 4) for i in core.noisy_order(shuf, "wave", freq=3, amp=1.0)]
assert a == b
print("  ok")

print("=== jitter: stable via ids, varies with seed ===")
ids = list(range(100, 120))
ja = [round(vals[i], 4) for i in core.noisy_order(vals, "jitter", amp=0.5, seed=3, ids=ids)]
pairs = list(zip(vals, ids)); random.Random(2).shuffle(pairs)
sv = [p[0] for p in pairs]; si = [p[1] for p in pairs]
jb = [round(sv[i], 4) for i in core.noisy_order(sv, "jitter", amp=0.5, seed=3, ids=si)]
assert ja == jb, "jitter not id-stable"
assert (core.noisy_order(vals, "jitter", amp=0.7, seed=1)
        != core.noisy_order(vals, "jitter", amp=0.7, seed=2))
print("  ok")

print("=== phase shifts the wave ===")
p0 = core.noisy_order(vals, "wave", freq=3, amp=1.0, phase=0.0)
p1 = core.noisy_order(vals, "wave", freq=3, amp=1.0, phase=1.5)
assert p0 != p1
print("  ok")

print("=== degenerate sizes ===")
assert core.noisy_order([], "wave") == []
assert core.noisy_order([0.5], "wave") == [0]
print("  ok")

print("\nALL NOISE TESTS PASSED")
