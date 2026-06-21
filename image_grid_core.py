"""
Core logic for the Image Grid Maker.

Pure (no GUI) functions so they can be unit-tested headlessly and used by
multiprocessing workers. Requires: Pillow.
"""

import os
from datetime import datetime
from collections import Counter
from fractions import Fraction
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageOps

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

    def sort_key(self):
        # Sub-folder (by name) -> Date Taken -> file name (when no date).
        has_date = 0 if self.taken is not None else 1
        date_val = self.taken if self.taken is not None else datetime.min
        return (self.folder.lower(), has_date, date_val, self.name.lower())


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

    def _add(rec, i):
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
            _add(_probe(item), i)
            if progress and (i % 50 == 0 or i == total - 1):
                progress(i + 1, total)
    else:
        chunk = max(1, total // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, rec in enumerate(ex.map(_probe, files, chunksize=chunk)):
                _add(rec, i)
                if progress and (i % 50 == 0 or i == total - 1):
                    progress(i + 1, total)
    return photos


# ----------------------------------------------------------------------------
# Aspect ratios
# ----------------------------------------------------------------------------

def ratio_label(ar):
    """Human label for an aspect ratio, e.g. 1.5 -> '3:2 (1.50)'."""
    frac = Fraction(ar).limit_denominator(20)
    return "%d:%d (%.2f)" % (frac.numerator, frac.denominator, ar)


def aspect_histogram(photos):
    """
    Group photos by rounded aspect ratio.
    Returns a list of dicts sorted by count desc:
        {'bucket': float, 'count': int, 'ar': float (median), 'label': str}
    """
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
# Grid layout
# ----------------------------------------------------------------------------

def best_grid(target_count, available, cell_ar, target_out_ar):
    """
    Find (cols, rows, used) forming an exact rectangle whose output aspect
    ratio is closest to target_out_ar, using close to target_count cells
    (never more than `available`).
    """
    n = max(1, min(target_count, available))
    best = None
    for cols in range(1, available + 1):
        for rows in {n // cols, -(-n // cols)}:  # floor, ceil
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
    """Derive uniform cell pixel size from the desired total grid width."""
    bw = max(0, int(border))
    inner = grid_width - (cols + 1) * bw
    cell_w = max(1, int(round(inner / cols)))
    cell_h = max(1, int(round(cell_w / cell_ar)))
    return cell_w, cell_h


# ----------------------------------------------------------------------------
# Cropping + compositing  (parallel)
# ----------------------------------------------------------------------------

def _center_crop_to_ratio(im, target_ar):
    w, h = im.size
    cur = w / h
    if abs(cur - target_ar) < 1e-6:
        return im
    if cur > target_ar:          # too wide -> trim width
        new_w = int(round(h * target_ar))
        x = (w - new_w) // 2
        return im.crop((x, 0, x + new_w, h))
    else:                        # too tall -> trim height
        new_h = int(round(w / target_ar))
        y = (h - new_h) // 2
        return im.crop((0, y, w, y + new_h))


def _render_cell(args):
    """Worker: open, orient, crop-to-ratio and resize one photo.
    Returns (cell_w, cell_h, raw_rgb_bytes) or None on failure."""
    path, cw, ch, target_ar = args
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = _center_crop_to_ratio(im, target_ar)
            im = im.resize((cw, ch), Image.LANCZOS)
            return (cw, ch, im.tobytes())
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


def build_grid(selected, cols, rows, cell_w, cell_h, cell_ar,
               border=0, border_color="#000000", progress=None, workers=None):
    """Composite selected photos into an exact grid image (parallel rendering)."""
    bw = max(0, int(border))
    total_w = cols * cell_w + (cols + 1) * bw
    total_h = rows * cell_h + (rows + 1) * bw
    bg = _parse_color(border_color) if bw > 0 else (255, 255, 255)
    canvas = Image.new("RGB", (total_w, total_h), bg)

    n = min(len(selected), cols * rows)
    tasks = [(selected[i].path, cell_w, cell_h, cell_ar) for i in range(n)]

    def _place(idx, rec):
        if rec is None:
            return
        cw, ch, data = rec
        r, c = divmod(idx, cols)
        x = bw + c * (cell_w + bw)
        y = bw + r * (cell_h + bw)
        cell = Image.frombytes("RGB", (cw, ch), data)
        canvas.paste(cell, (x, y))

    if workers is None:
        workers = n_workers()

    if workers <= 1 or n < PARALLEL_THRESHOLD:
        for idx in range(n):
            _place(idx, _render_cell(tasks[idx]))
            if progress and (idx % 5 == 0 or idx == n - 1):
                progress(idx + 1, n)
    else:
        chunk = max(1, n // (workers * 8))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for idx, rec in enumerate(ex.map(_render_cell, tasks, chunksize=chunk)):
                _place(idx, rec)
                if progress and (idx % 5 == 0 or idx == n - 1):
                    progress(idx + 1, n)

    return canvas


def save_image(img, path, fmt="JPEG", quality=90):
    fmt = fmt.upper()
    if fmt in ("JPG", "JPEG"):
        img.save(path, "JPEG", quality=int(quality), optimize=True)
    else:
        img.save(path, "PNG", optimize=True)
