"""Tests for v1.0.4 core: Lab, dominant/per-photo colour, similarity path,
noise field, and use-both mixed classification."""
import os, shutil
from PIL import Image
import image_grid_core as core

TMP = "/tmp/v104"; shutil.rmtree(TMP, ignore_errors=True)


def mk(path, w, h, rgb):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), rgb).save(path, "JPEG", quality=95)


print("=== rgb_to_lab sanity ===")
assert abs(core.rgb_to_lab((0, 0, 0))[0]) < 1.0            # black L*~0
assert core.rgb_to_lab((255, 255, 255))[0] > 99            # white L*~100
Lr = core.rgb_to_lab((255, 0, 0)); Lg = core.rgb_to_lab((0, 255, 0))
assert Lr[1] > 40 and Lr[2] > 20                            # red: +a*, +b*
assert Lg[1] < -40                                          # green: -a*
print("  black/white/red/green LAB OK")

print("=== color_sort_key uses Lab (brightness = L*, monotonic) ===")
vals = [core.color_sort_key((v, v, v), "brightness")[0] for v in (0, 64, 128, 192, 255)]
assert vals == sorted(vals) and vals[0] < 5 and vals[-1] > 95
print("  grey ramp L*:", [round(v, 1) for v in vals])

print("=== dominant colour: picks the majority colour, not the average ===")
# image that is 90% red, 10% blue -> dominant red, average would be purple-ish
im = Image.new("RGB", (100, 100), (220, 20, 20))
for y in range(100):
    for x in range(90, 100):
        im.putpixel((x, y), (20, 20, 220))
os.makedirs(TMP, exist_ok=True)
im.save(f"{TMP}/mix.jpg", "JPEG", quality=95)
dom = core._photo_dominant(f"{TMP}/mix.jpg")
avg = core._photo_avg(f"{TMP}/mix.jpg")
assert dom[0] > dom[2], (dom,)                    # dominant is red-ish
print("  dominant=%s  average=%s" % (dom, avg))

print("=== scan_photo_colors: per-photo dict ===")
mk(f"{TMP}/a/r.jpg", 800, 600, (200, 30, 30))
mk(f"{TMP}/a/g.jpg", 800, 600, (30, 200, 30))
mk(f"{TMP}/a/b.jpg", 800, 600, (30, 30, 200))
photos = core.scan_folders([f"{TMP}/a"], False, workers=1)
pc = core.scan_photo_colors(photos, source="average", workers=1)
assert len(pc) == 3 and all(p.path in pc for p in photos)
print("  ", {os.path.basename(k): v for k, v in pc.items()})

print("=== similarity_path: consecutive items are near in Lab ===")
# a shuffled rainbow; greedy path should reduce total step distance vs original
import colorsys
rgbs = [tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h / 12.0, 0.9, 0.9))
        for h in range(12)]
import random
random.Random(0).shuffle(rgbs)
labs = [core.rgb_to_lab(c) for c in rgbs]
order = core.similarity_path(labs)
assert sorted(order) == list(range(12))
def total(seq):
    return sum(core.lab_distance(labs[seq[i]], labs[seq[i + 1]])
               for i in range(len(seq) - 1))
assert total(order) < total(list(range(12))), (total(order), total(list(range(12))))
print("  path dist %.0f < original %.0f" % (total(order), total(list(range(12)))))

# (noise_field removed in v1.0.5 — replaced by reference-image ordering; see test_reference.py)

print("=== select_and_classify_multi: dominant vs use_both ===")
# folder with 5 landscapes + 3 portraits
for i in range(5): mk(f"{TMP}/mixset/l_{i}.jpg", 900, 600, (100, 100, 100))
for i in range(3): mk(f"{TMP}/mixset/p_{i}.jpg", 600, 900, (100, 100, 100))
fp = core.scan_folders([f"{TMP}/mixset"], False, workers=1)
dom = core.select_and_classify_multi(fp, None, use_both=False)
assert len(dom) == 1 and dom[0][0] == "H" and len(dom[0][1]) == 5, dom
both = core.select_and_classify_multi(fp, None, use_both=True)
assert [s[0] for s in both] == ["H", "V"], both          # horizontals first
assert len(both[0][1]) == 5 and len(both[1][1]) == 3
print("  dominant -> H(5);  both -> H(5) then V(3)")

print("=== photos_to_groups: whole groups, remainder dropped ===")
g = core.photos_to_groups(list(range(7)), 3, "H")
assert [x[1] for x in g] == [[0, 1, 2], [3, 4, 5]] and all(x[0] == "H" for x in g)
print("  ok")

print("\nALL V1.0.4 CORE TESTS PASSED")
