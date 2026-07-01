"""Tests for v1.0.5 reference-image ordering (core primitives)."""
import os, shutil
from PIL import Image
import image_grid_core as core

TMP = "/tmp/vref"; shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)

print("=== ref_scalar: brightness = L*, colour = warm/cool ===")
assert core.ref_scalar((0, 0, 0), "brightness") < 5
assert core.ref_scalar((255, 255, 255), "brightness") > 95
warm_red = core.ref_scalar((255, 0, 0), "color")
cool_blue = core.ref_scalar((0, 0, 255), "color")
assert warm_red > cool_blue, (warm_red, cool_blue)      # red bright, blue dark
assert abs(core.ref_scalar((128, 128, 128), "color")) < 0.01   # grey ~ neutral
print("  red=%.2f blue=%.2f grey~0" % (warm_red, cool_blue))

print("=== match_to_targets: darkest item -> darkest cell ===")
scalars = [50, 10, 90, 30]         # item brightnesses
targets = [0.9, 0.1, 0.5, 0.2]     # cell targets (cell0 bright ... cell1 dark)
res = core.match_to_targets(scalars, targets)   # res[cell] = item idx
assert sorted(res) == [0, 1, 2, 3]
# darkest item (idx1, val10) -> darkest cell (cell1, .1)
assert res[1] == 1
# brightest item (idx2, val90) -> brightest cell (cell0, .9)
assert res[0] == 2
print("  ", res)

print("=== reference_targets_2d: gradient sampled row-major, crop vs stretch ===")
# horizontal black->white gradient, 100x100
g = Image.new("L", (100, 100))
for x in range(100):
    for y in range(100):
        g.putpixel((x, y), int(x / 99 * 255))
t = core.reference_targets_2d(g, 4, 2, out_ar=2.0, fit="stretch")
assert len(t) == 8
# row-major: within each row, left (dark) -> right (bright), increasing
assert t[0] < t[1] < t[2] < t[3]
assert all(0.0 <= v <= 1.0 for v in t)
ti = core.reference_targets_2d(g, 4, 2, fit="stretch", invert=True)
assert ti[0] > ti[3]                 # inverted
print("  row0:", [round(v, 2) for v in t[:4]], " inverted row0:", [round(v, 2) for v in ti[:4]])

print("=== reference_targets_1d: vertical sweep of N values ===")
gv = Image.new("L", (10, 100))
for y in range(100):
    for x in range(10):
        gv.putpixel((x, y), int(y / 99 * 255))
v = core.reference_targets_1d(gv, 5)
assert len(v) == 5 and v[0] < v[-1]      # top dark -> bottom bright
print("  ", [round(x, 2) for x in v])

print("=== end-to-end: order items to a gradient reference ===")
# 4 grey photos of increasing brightness; reference bright-left gradient (2x2)
rgbs = [(20, 20, 20), (90, 90, 90), (160, 160, 160), (230, 230, 230)]
scal = [core.ref_scalar(c, "brightness") for c in rgbs]
tg = core.reference_targets_2d(g, 2, 2, fit="stretch")   # left dark, right bright
place = core.match_to_targets(scal, tg)   # place[cell]=item
# top-left cell (darkest target) should get the darkest photo (idx0)
darkest_cell = min(range(4), key=lambda i: tg[i])
assert place[darkest_cell] == 0
print("  placement:", place, " targets:", [round(x, 2) for x in tg])

print("=== reduce_targets: equal reading-order bands ===")
rt = core.reduce_targets([0.0, 0.2, 0.4, 0.6, 0.8, 1.0], 3)
assert all(abs(a - b) < 1e-9 for a, b in zip(rt, [0.1, 0.5, 0.9])), rt
assert core.reduce_targets([0.5], 3) == [0.5, 0.5, 0.5]
assert core.reduce_targets([], 3) == []
print("  ", [round(x, 3) for x in rt])

print("\nALL REFERENCE TESTS PASSED")
