"""Tests for v1.0.3: set-colour scanning, sampling, and colour ordering."""
import os, shutil
from PIL import Image
import image_grid_core as core

TMP = "/tmp/v103"; shutil.rmtree(TMP, ignore_errors=True)


def mk(path, w, h, rgb):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), rgb).save(path, "JPEG", quality=95)


# Three sets, each a solid colour: red, green, dark grey.
for i in range(4):
    mk(f"{TMP}/red/r{i}.jpg", 1200, 800, (220, 30, 30))
for i in range(4):
    mk(f"{TMP}/green/g{i}.jpg", 1200, 800, (30, 200, 30))
for i in range(4):
    mk(f"{TMP}/grey/y{i}.jpg", 1200, 800, (40, 40, 40))

photos = core.scan_folders([TMP], True, workers=1)
by_folder = {}
for p in photos:
    by_folder.setdefault(os.path.normcase(os.path.abspath(p.folder)), []).append(p)
sets = list(by_folder.items())

print("=== scan_set_colors: all photos ===")
cols = core.scan_set_colors(sets, sample=None, workers=1)
assert len(cols) == 3, cols
keys = {os.path.basename(k.rstrip(os.sep)): v for k, v in cols.items()}
# JPEG is lossy; allow a tolerance around the source solid colour.
for name, want in [("red", (220, 30, 30)), ("green", (30, 200, 30)),
                   ("grey", (40, 40, 40))]:
    got = keys[name]
    assert all(abs(a - b) <= 12 for a, b in zip(got, want)), (name, got, want)
print("  ", keys)

print("=== scan_set_colors: evenly-spaced sample (N=2) ===")
cols2 = core.scan_set_colors(sets, sample=2, workers=1)
assert len(cols2) == 3
# Same solid colour -> sampling gives the same averages within tolerance.
for k in cols:
    assert all(abs(a - b) <= 4 for a, b in zip(cols[k], cols2[k])), (k, cols[k], cols2[k])

print("=== _even_sample picks the right count, evenly ===")
seq = list(range(10))
assert core._even_sample(seq, None) == seq
assert core._even_sample(seq, 5) == [0, 2, 4, 6, 8]
assert core._even_sample(seq, 3) == [0, 3, 6]
assert len(core._even_sample(seq, 100)) == 10

print("=== color_sort_key: brightness orders grey<red<green here ===")
order = sorted(["red", "green", "grey"],
               key=lambda n: core.color_sort_key(keys[n], "brightness"))
# luma: grey=40, red≈0.299*220≈73, green≈0.587*200≈121
assert order == ["grey", "red", "green"], order
print("  brightness order:", order)

print("=== color_sort_key: colour (hue) separates red vs green ===")
hr = core.color_sort_key(keys["red"], "color")[0]
hg = core.color_sort_key(keys["green"], "color")[0]
assert hr < hg, (hr, hg)   # red hue (~0) < green hue (~0.33)
print("  hue red=%.3f green=%.3f" % (hr, hg))

print("\nALL V1.0.3 TESTS PASSED")
