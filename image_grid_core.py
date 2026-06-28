"""
Core logic for the Image Grid Maker.

Pure (no GUI) functions so they can be unit-tested headlessly and used by
multiprocessing workers. Requires: Pillow.
"""

import os
import math
import random
import colorsys
from datetime import datetime
from collections import Counter
from fractions import Fraction
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageOps, ImageFile

# Robustness for large photo sets: tolerate slightly truncated JPEGs and do not
# reject very large (photogrammetry / stitched) images. Without these, such
# images raise inside the worker and the cell silently renders blank.
ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = None

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

ASPECT_BUCKET_DECIMALS = 2        # ratios rounded to this many decimals to group
EXIF_DATETIME_ORIGINAL = 36867    # DateTimeOriginal
EXIF_DATETIME = 306               # DateTime

# Jobs smaller than this run sequentially (avoids pool start-up overhead).
PARALLEL_THRESHOLD = 64


def n_workers(fraction=0.8):
    """Number of worker processes = fraction of available cores (>=1)."""
    cores = os.cpu_count() or 1
    return max(1, int(round(cores * fraction)))


# ----------------------------------------------------------------------------
# Photo record
# ----------------------------------------------------------------------------

class Photo:
    __slots__ = ("path", "folder", "name", "width", "height", "aspect", "taken")

    def __init__(self, path, folder, name, width, height, taken):
        self.path = path
        self.folder = folder
        self.name = name
        self.width = width
        self.height = height
        self.aspect = width / height
        self.taken = taken

    @property
    def bucket(self):
        return round(self.aspect, ASPECT_BUCKET_DECIMALS)

    @property
    def is_landscape(self):
        return self.aspect >= 1.0

    def within_folder_key(self):
        has_date = 0 if self.taken is not None else 1
        return (has_date, self.taken if self.taken is not None else datetime.min,
                self.name.lower())

    def sort_key(self):
        return (self.folder.lower(),) + self.within_folder_key()


# ----------------------------------------------------------------------------
# EXIF helpers
# ----------------------------------------------------------------------------

def _read_exif_date(img):
    try:
        exif = img.getexif()
    except Exception:
        return None
    for tag in (EXIF_DATETIME_ORIGINAL, EXIF_DATETIME):
        val = exif.get(tag)
        if val:
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(str(val).strip(), fmt)
                except ValueError:
                    continue
    return None


def _oriented_size(img):
    w, h = img.size
    try:
        orientation = img.getexif().get(274)
    except Exception:
        orientation = None
    if orientation in (5, 6, 7, 8):
        return h, w
    return w, h


# ----------------------------------------------------------------------------
# Scanning  (parallel)
# ----------------------------------------------------------------------------

def _probe(item):
    """Worker: read size + EXIF date for one file. Returns a tuple or None."""
    dirpath, fn = item
    full = os.path.join(dirpath, fn)
    try:
        with Image.open(full) as img:
            w, h = _oriented_size(img)
            taken = _read_exif_date(img)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return (full, dirpath, fn, w, h, taken)


def _list_files(roots, include_subfolders):
    files = []
    for root in roots:
        if include_subfolders:
            for dirpath, _dirs, filenames in os.walk(root):
                for fn in filenames:
                    if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                        files.append((dirpath, fn))
        else:
            try:
                for fn in os.listdir(root):
                    full = os.path.join(root, fn)
                    if os.path.isfile(full) and os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                        files.append((root, fn))
            except OSError:
                pass
    return files


def scan_folders(roots, include_subfolders=True, progress=None, workers=None):
    """Walk folders and return a list of Photo objects (parallel metadata read)."""
    files = _list_files(roots, include_subfolders)
    total = len(files)
    if total == 0:
        return []

    if workers is None:
        workers = n_workers()

    photos = []
    seen = set()

    def _add(rec):
        if rec is None:
            return
        full, dirpath, fn, w, h, taken = rec
        key = os.path.normcase(os.path.abspath(full))
        if key in seen:
            return
        seen.add(key)
        photos.append(Photo(full, dirpath, fn, w, h, taken))

    if workers <= 1 or total < PARALLEL_THRESHOLD:
        for i, item in enumerate(files):
            _add(_probe(item))
            if progress and (i % 50 == 0 or i == total - 1):
                progress(i + 1, total)
    else:
        chunk = max(1, total // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, rec in enumerate(ex.map(_probe, files, chunksize=chunk)):
                _add(rec)
                if progress and (i % 50 == 0 or i == total - 1):
                    progress(i + 1, total)
    return photos


# ----------------------------------------------------------------------------
# Ordering
# ----------------------------------------------------------------------------

def order_photos(photos, by="name", descending=False, seed=0):
    """Sub-folders ordered by name/created/random; within each, Date Taken/name."""
    folders = sorted({p.folder for p in photos}, key=lambda f: f.lower())
    if by == "created":
        def fkey(f):
            try:
                return os.path.getctime(f)
            except OSError:
                return 0.0
        ordered = sorted(folders, key=fkey)
    elif by == "random":
        ordered = folders[:]
        random.Random(seed).shuffle(ordered)
    else:
        ordered = folders
    if descending:
        ordered = list(reversed(ordered))
    rank = {f: i for i, f in enumerate(ordered)}
    return sorted(photos, key=lambda p: (rank[p.folder],) + p.within_folder_key())


def dirs_with_images(root, recursive=True):
    """Directories that directly contain >=1 image (root included). Sorted by name."""
    out = []
    if recursive:
        for dirpath, _dirs, files in os.walk(root):
            if any(os.path.splitext(f)[1].lower() in IMAGE_EXTS for f in files):
                out.append(dirpath)
    else:
        try:
            if any(os.path.splitext(f)[1].lower() in IMAGE_EXTS
                   for f in os.listdir(root)
                   if os.path.isfile(os.path.join(root, f))):
                out.append(root)
        except OSError:
            pass
    return sorted(set(out), key=lambda d: d.lower())


def order_by_folder_list(photos, folders):
    """Order photos by the explicit folder list order, then Date Taken / name."""
    rank = {os.path.normcase(os.path.abspath(f)): i for i, f in enumerate(folders)}
    big = len(folders)
    def key(p):
        r = rank.get(os.path.normcase(os.path.abspath(p.folder)), big)
        return (r,) + p.within_folder_key()
    return sorted(photos, key=key)


# ----------------------------------------------------------------------------
# Set colours (average colour per set, for ordering + preview)
# ----------------------------------------------------------------------------

def _photo_avg(path):
    """Average RGB of one image, decoded tiny for speed/memory. None on failure."""
    try:
        with Image.open(path) as im:
            try:
                im.draft("RGB", (32, 32))
            except Exception:
                pass
            im = im.convert("RGB").resize((1, 1), Image.LANCZOS)
            return im.getpixel((0, 0))
    except Exception:
        return None


def _even_sample(photos, sample):
    """Up to `sample` photos, evenly spaced. sample=None -> all photos."""
    n = len(photos)
    if sample is None or sample >= n:
        return list(photos)
    if sample <= 0:
        return []
    step = n / sample
    return [photos[int(i * step)] for i in range(sample)]


def scan_set_colors(sets, sample=None, progress=None, workers=None):
    """Average colour per set.

    sets: list of (key, [Photo]). For each set the photos are ordered by Date
    Taken/name, then `sample` of them are taken evenly spaced (sample=None ->
    all photos) and averaged. Returns {key: (r, g, b)}.
    """
    tasks = []          # flat (key, path) list, preserves order for ex.map
    for key, photos in sets:
        ordered = sorted(photos, key=lambda p: p.within_folder_key())
        for p in _even_sample(ordered, sample):
            tasks.append((key, p.path))
    total = len(tasks)
    sums = {}           # key -> [r, g, b, count]

    def _acc(key, c):
        if c is None:
            return
        s = sums.setdefault(key, [0, 0, 0, 0])
        s[0] += c[0]; s[1] += c[1]; s[2] += c[2]; s[3] += 1

    if workers is None:
        workers = n_workers()
    paths = [t[1] for t in tasks]

    if total == 0:
        return {}
    if workers <= 1 or total < PARALLEL_THRESHOLD:
        for i, (key, path) in enumerate(tasks):
            _acc(key, _photo_avg(path))
            if progress and (i % 25 == 0 or i == total - 1):
                progress(i + 1, total)
    else:
        chunk = max(1, total // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, c in enumerate(ex.map(_photo_avg, paths, chunksize=chunk)):
                _acc(tasks[i][0], c)
                if progress and (i % 25 == 0 or i == total - 1):
                    progress(i + 1, total)

    out = {}
    for key, s in sums.items():
        if s[3] > 0:
            out[key] = (round(s[0] / s[3]), round(s[1] / s[3]), round(s[2] / s[3]))
    return out


def color_sort_key(rgb, by="brightness"):
    """Sort key for an (r, g, b) set colour.
    by='color' -> hue, then saturation, then value (rainbow-ish ordering).
    by='brightness' -> perceived luminance (Rec. 601)."""
    r, g, b = (c / 255.0 for c in rgb)
    if by == "color":
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        return (h, s, v)
    return (0.299 * r + 0.587 * g + 0.114 * b,)


# ----------------------------------------------------------------------------
# Aspect ratios
# ----------------------------------------------------------------------------

def ratio_label(ar):
    """Human label for an aspect ratio, e.g. 1.5 -> '3:2 (1.50)'."""
    frac = Fraction(ar).limit_denominator(20)
    return "%d:%d (%.2f)" % (frac.numerator, frac.denominator, ar)


def aspect_histogram(photos):
    """Group photos by rounded aspect ratio; list of dicts sorted by count desc."""
    groups = {}
    for p in photos:
        groups.setdefault(p.bucket, []).append(p.aspect)
    out = []
    for bucket, ars in groups.items():
        ars.sort()
        med = ars[len(ars) // 2]
        out.append({"bucket": bucket, "count": len(ars),
                    "ar": med, "label": ratio_label(med)})
    out.sort(key=lambda d: d["count"], reverse=True)
    return out


def dominant_bucket(photos):
    if not photos:
        return None
    return Counter(p.bucket for p in photos).most_common(1)[0][0]


def filter_by_buckets(photos, buckets):
    buckets = set(buckets)
    return [p for p in photos if p.bucket in buckets]


# ----------------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------------

def select_photos(photos, count, method="first"):
    """photos must already be sorted. Returns up to `count` photos."""
    n = len(photos)
    if count >= n:
        return list(photos)
    if method == "evenly":
        step = n / count
        return [photos[int(i * step)] for i in range(count)]
    return list(photos[:count])


# ----------------------------------------------------------------------------
# Slots
# ----------------------------------------------------------------------------

def make_slots(photos, mixed=False):
    """Landscapes fill a slot; in mixed mode two portraits share one slot."""
    if not mixed:
        return [("L", p, None) for p in photos]
    slots = []
    buf = []
    for p in photos:
        if p.is_landscape:
            slots.append(("L", p, None))
        else:
            buf.append(p)
            if len(buf) == 2:
                slots.append(("P", buf[0], buf[1]))
                buf = []
    return slots  # a single leftover portrait is intentionally dropped


def count_photos_in_slots(slots):
    return sum(1 if s[0] == "L" else 2 for s in slots)


# ----------------------------------------------------------------------------
# Grid layout
# ----------------------------------------------------------------------------

def best_grid(target_count, available, cell_ar, target_out_ar):
    """Closest exact rectangle to target_out_ar using close to target_count cells."""
    n = max(1, min(target_count, available))
    best = None
    for cols in range(1, available + 1):
        for rows in {n // cols, -(-n // cols)}:
            if rows < 1:
                continue
            used = cols * rows
            if used > available:
                continue
            out_ar = (cols * cell_ar) / rows
            aspect_err = abs(out_ar - target_out_ar) / target_out_ar
            count_err = abs(used - n) / n
            cost = aspect_err + 0.5 * count_err
            cand = (cost, aspect_err, -used, cols, rows)
            if best is None or cand < best:
                best = cand
    _, _, neg_used, cols, rows = best
    return cols, rows, -neg_used


def cell_size_from_width(grid_width, cols, cell_ar, border):
    """Derive uniform cell (slot) pixel size from the desired total grid width."""
    bw = max(0, int(border))
    inner = grid_width - (cols + 1) * bw
    cell_w = max(1, int(round(inner / cols)))
    cell_h = max(1, int(round(cell_w / cell_ar)))
    return cell_w, cell_h


def fit_exact(img, width, target_ar):
    """Resize the finished grid to exactly width x round(width/target_ar)."""
    w = max(1, int(round(width)))
    h = max(1, int(round(w / target_ar)))
    if img.size == (w, h):
        return img
    return img.resize((w, h), Image.LANCZOS)


# ----------------------------------------------------------------------------
# Cropping + compositing  (parallel)
# ----------------------------------------------------------------------------

def _center_crop_to_ratio(im, target_ar):
    w, h = im.size
    cur = w / h
    if abs(cur - target_ar) < 1e-6:
        return im
    if cur > target_ar:
        new_w = int(round(h * target_ar))
        x = (w - new_w) // 2
        return im.crop((x, 0, x + new_w, h))
    new_h = int(round(w / target_ar))
    y = (h - new_h) // 2
    return im.crop((0, y, w, y + new_h))


def _open_crop_resize(path, w, h):
    """Open, orient, centre-crop to w:h, resize to (w, h).
    Uses Image.draft so big JPEGs decode at a reduced scale -> far less memory
    (the main cause of dropped cells on huge photo sets) and faster."""
    try:
        with Image.open(path) as im:
            try:
                im.draft("RGB", (max(1, w * 2), max(1, h * 2)))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = _center_crop_to_ratio(im, w / h)
            return im.resize((w, h), Image.LANCZOS)
    except Exception:
        return None


def _parse_color(color):
    if isinstance(color, (tuple, list)):
        return tuple(color)
    color = color.strip()
    if color.startswith("#"):
        color = color[1:]
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    return color


def _render_slot(args):
    """Worker: render one slot to a (cell_w x cell_h) RGB byte buffer."""
    kind, p1, p2, cw, ch, b, bg = args
    cell = Image.new("RGB", (cw, ch), bg)
    if kind == "L":
        im = _open_crop_resize(p1, cw, ch)
        if im is not None:
            cell.paste(im, (0, 0))
    else:
        vl = max(1, (cw - b) // 2)
        vr = max(1, cw - b - vl)
        im1 = _open_crop_resize(p1, vl, ch)
        if im1 is not None:
            cell.paste(im1, (0, 0))
        im2 = _open_crop_resize(p2, vr, ch)
        if im2 is not None:
            cell.paste(im2, (vl + b, 0))
    return cell.tobytes()


def build_slots_image(slots, cols, rows, cell_w, cell_h,
                      border=0, border_color="#000000", progress=None, workers=None):
    """Composite slots into an exact grid image (parallel rendering)."""
    b = max(0, int(border))
    bg = _parse_color(border_color) if b > 0 else (255, 255, 255)
    total_w = cols * cell_w + (cols + 1) * b
    total_h = rows * cell_h + (rows + 1) * b
    canvas = Image.new("RGB", (total_w, total_h), bg)

    n = min(len(slots), cols * rows)
    tasks = []
    for i in range(n):
        s = slots[i]
        if s[0] == "L":
            tasks.append(("L", s[1].path, None, cell_w, cell_h, b, bg))
        else:
            tasks.append(("P", s[1].path, s[2].path, cell_w, cell_h, b, bg))

    def _place(idx, data):
        r, c = divmod(idx, cols)
        x = b + c * (cell_w + b)
        y = b + r * (cell_h + b)
        canvas.paste(Image.frombytes("RGB", (cell_w, cell_h), data), (x, y))

    if workers is None:
        workers = n_workers()

    if workers <= 1 or n < PARALLEL_THRESHOLD:
        for idx in range(n):
            _place(idx, _render_slot(tasks[idx]))
            if progress and (idx % 5 == 0 or idx == n - 1):
                progress(idx + 1, n)
    else:
        chunk = max(1, n // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for idx, data in enumerate(ex.map(_render_slot, tasks, chunksize=chunk)):
                _place(idx, data)
                if progress and (idx % 5 == 0 or idx == n - 1):
                    progress(idx + 1, n)
    return canvas


def build_grid(selected, cols, rows, cell_w, cell_h, cell_ar=None,
               border=0, border_color="#000000", progress=None, workers=None):
    """Back-compatible single-photo grid (each photo fills one slot)."""
    slots = [("L", p, None) for p in selected]
    return build_slots_image(slots, cols, rows, cell_w, cell_h,
                             border, border_color, progress, workers)


# ----------------------------------------------------------------------------
# Mixed mode (set-based): one folder = one image set
# ----------------------------------------------------------------------------

# r -> (landscapes per horizontal group, portraits per vertical group)
GROUP_SIZES = {"1/2": (1, 2), "3/5": (3, 5), "2/3": (2, 3)}
R_VALUES = {"1/2": 0.5, "3/5": 0.6, "2/3": 2.0 / 3.0}
MIN_SET_IMAGES = 15


def classify_set(photos):
    """Classify a folder's photos by dominant orientation.
    Returns ('H'|'V', kept_photos) where kept are only the dominant orientation,
    sorted by Date Taken (EXIF) then file name. Ties go to horizontal."""
    land = [p for p in photos if p.is_landscape]
    port = [p for p in photos if not p.is_landscape]
    if len(land) >= len(port):
        kind, keep = "H", land
    else:
        kind, keep = "V", port
    keep = sorted(keep, key=lambda p: p.within_folder_key())
    return kind, keep


def mixed_validity(A, r_key):
    """(ok, balanced_crop). ok means A is wide enough for r (no upscaling)."""
    r = R_VALUES[r_key]
    retained = 1.0 / (A * math.sqrt(r))
    balanced = 1.0 - retained
    return balanced >= -1e-9, balanced


def mixed_cell_ar(r_key):
    """Group-cell width:height (borderless). gh/sqrt(r) == gv*sqrt(r)."""
    gh, _gv = GROUP_SIZES[r_key]
    return gh / math.sqrt(R_VALUES[r_key])


def select_and_classify(folder_photos, count, method="first"):
    """Per folder, in folder order: sort by Date Taken/name, apply the user's
    photo-count selection FIRST (First N / Evenly spaced), then classify the
    selected subset by dominant orientation. count=None means use all."""
    ordered = sorted(folder_photos, key=lambda p: p.within_folder_key())
    if count is None or count >= len(ordered):
        sel = ordered
    else:
        sel = select_photos(ordered, count, method)
    return classify_set(sel)


def build_mixed_groups(sets, r_key):
    """sets: list of (kind, photos) in folder order (already classified & sorted).
    Returns a flat list of groups in folder order; each group is (kind, [photos])
    of size gh (H) or gv (V). Each set is trimmed from the END to a whole number
    of groups; sets with < MIN_SET_IMAGES usable images are skipped."""
    gh, gv = GROUP_SIZES[r_key]
    groups = []
    for kind, photos in sets:
        gsize = gh if kind == "H" else gv
        usable = (len(photos) // gsize) * gsize
        if usable < MIN_SET_IMAGES:
            continue
        kept = photos[:usable]
        for i in range(0, usable, gsize):
            groups.append((kind, kept[i:i + gsize]))
    return groups


def count_photos_in_groups(groups):
    return sum(len(g[1]) for g in groups)


def _render_group(args):
    """Worker: render one group cell = N tiles side by side, borders between."""
    paths, cw, ch, b, bg = args
    n = len(paths)
    cell = Image.new("RGB", (cw, ch), bg)
    inner = cw - (n - 1) * b
    base = max(1, inner // n)
    widths = [base] * (n - 1) + [max(1, cw - (base + b) * (n - 1))]
    x = 0
    for path, w in zip(paths, widths):
        im = _open_crop_resize(path, w, ch)
        if im is not None:
            cell.paste(im, (x, 0))
        x += w + b
    return cell.tobytes()


def build_mixed_image(groups, cols, rows, cell_w, cell_h,
                      border=0, border_color="#000000", progress=None, workers=None):
    """Composite group cells into an exact grid (parallel)."""
    b = max(0, int(border))
    bg = _parse_color(border_color) if b > 0 else (255, 255, 255)
    total_w = cols * cell_w + (cols + 1) * b
    total_h = rows * cell_h + (rows + 1) * b
    canvas = Image.new("RGB", (total_w, total_h), bg)

    n = min(len(groups), cols * rows)
    tasks = [(tuple(p.path for p in groups[i][1]), cell_w, cell_h, b, bg)
             for i in range(n)]

    def _place(idx, data):
        r, c = divmod(idx, cols)
        x = b + c * (cell_w + b)
        y = b + r * (cell_h + b)
        canvas.paste(Image.frombytes("RGB", (cell_w, cell_h), data), (x, y))

    if workers is None:
        workers = n_workers()
    if workers <= 1 or n < PARALLEL_THRESHOLD:
        for idx in range(n):
            _place(idx, _render_group(tasks[idx]))
            if progress and (idx % 5 == 0 or idx == n - 1):
                progress(idx + 1, n)
    else:
        chunk = max(1, n // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for idx, data in enumerate(ex.map(_render_group, tasks, chunksize=chunk)):
                _place(idx, data)
                if progress and (idx % 5 == 0 or idx == n - 1):
                    progress(idx + 1, n)
    return canvas


def save_image(img, path, fmt="JPEG", quality=90):
    fmt = fmt.upper()
    if fmt in ("JPG", "JPEG"):
        img.save(path, "JPEG", quality=int(quality), optimize=True)
    else:
        img.save(path, "PNG", optimize=True)
