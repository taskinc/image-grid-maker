# Image Grid Maker

> Turn thousands of photos (e.g. photogrammetry captures) into a single, clean
> grid image — always a perfect square or rectangle, no empty cells.

![Version](https://img.shields.io/badge/version-1.0.5-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

![Image Grid Maker — application window](assets/screenshot.jpg)

---

## What the app does

Image Grid Maker scans one or more folders of images and composites a chosen
number of them into one large grid. It is built for big photo sets (thousands of
files) and does the tedious parts for you:

- **Finds and groups by aspect ratio.** After scanning it lists every aspect
  ratio present with photo counts. You pick which to include; photos of other
  shapes are **centre-cropped** to a single cell ratio so the grid stays uniform.
- **Order sets or photos.** The **Order** panel (next to the preview) re-sequences the grid by **name, date, colour, brightness or similarity**, ascending/descending, plus **Randomise**. Choose **Sets** (order whole sub-folders; order inside each set stays Date-Taken→name) or **Photos** (ignore folders and place every photo individually).
- **Colours & perceptual similarity.** **Scan colours** reads a colour per set (**All** or an evenly-spaced **Sample of N**) or per photo, measured as the **Average** or the **Dominant** colour. Colour, Brightness and Similarity ordering use perceptual **CIELAB**; **Similarity** is a nearest-neighbour path so neighbouring tiles look alike. The live preview is a colour mosaic; until scanned, tiles use defaults (landscape 225,225,225; portrait 175,175,175).
- **Reference-image ordering.** Load a grayscale image and the app arranges photos to match it — dark photos land in the dark areas (for Colour, warm reds go bright and cool blues go dark). **Stretch** or **Crop** it to the grid; in **Photos** mode it's a full 2-D placement, in **Sets** mode whole sets follow the image's top-to-bottom sweep. Ascending/Descending inverts it, and **View reference** shows it resampled onto the grid.
- **Mixed orientation.** Combine landscape and portrait in one grid, packed in equal-width groups (base ratio A and width ratio r = 1/2, 3/5 or 2/3), always a perfect rectangle. Each folder is a set by dominant orientation, or tick **Use both orientations** to keep both (landscapes first, then portraits). In **Photos** order mode, folders are ignored — all photos are pooled by orientation and the group-cells are ordered by colour/brightness/similarity.
- **Pick how many and how.** Use the first *N* photos, or sample **evenly** across
  the whole set.
- **Exact grid, every time.** You give a target output aspect ratio (e.g. 16:9)
  and the app computes the closest rows × columns with **no empty cells**.
- **Uniform resolution.** You set the final image **width in pixels**; every cell
  is rendered at the same size regardless of the source resolution.
- **Output options.** JPEG (with quality) or PNG, an optional coloured border, and an exact-fit toggle to force the precise output size.
- **Fast.** Scanning and rendering run across multiple CPU cores (default 80%).
- **Convenient UI.** Drag-and-drop folders, a built-in live preview pane (resizable divider), per-section help (`?`) buttons, and a log panel.

---

## Requirements

- **Windows** with **Python 3.8+** (Tkinter is included with the standard
  Python installer).
- Python packages: **Pillow** and **tkinterdnd2** (see `requirements.txt`).

```bash
pip install -r requirements.txt
```

> If `tkinterdnd2` is missing the app still runs, but folder drag-and-drop is
> disabled (a hint is shown instead).

---

## Installation

### Option A — Download and run (recommended)

Download the latest **`ImageGridMaker.exe`** from the
[**Releases**](https://github.com/taskinc/image-grid-maker/releases) page and
double-click it. No Python needed.

> On first launch Windows SmartScreen may warn about an unsigned app — choose
> *More info → Run anyway*.

### Option B — Run from source

```bash
pip install -r requirements.txt
python image_grid_maker.py
```

### Building the .exe yourself (optional)

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --clean --onefile --windowed --name ImageGridMaker ^
  --collect-all tkinterdnd2 image_grid_maker.py
```

## Usage

1. **Source folders** — drag folders onto the window, or click *Add folder*.
   Sub-folders are included by default.
2. **Scan & analyse** — reads every image and groups it by aspect ratio.
3. **Aspect ratios** — ratios are split into **Landscape** and **Portrait**; tick the ones to include and the ratio to *crop all included photos to*. For **Mixed mode** (combine landscape + portrait folders), tick at least one of each and set the base ratio A and width ratio r.
4. **Photo selection** — set how many photos, and *First N* vs *Evenly spaced*.
5. **Output layout** — type the target aspect ratio; the app shows the exact grid.
6. **Resolution & format** — set the output width (px), and JPEG/PNG + quality.
7. **Border** — optional width (0 = none) and colour.
8. **Performance** — the percentage of CPU cores to use.

The **live preview pane** on the right shows the exact grid as you change options (drag the divider to resize it), with each tile filled by its set's colour. Use **Order sets** above it to re-sequence folders (by name, date, colour, brightness, or randomise) and **Scan colours** to compute set colours. Then click **Generate grid…**. Every group has a **?** button explaining its options, and the **Log** panel records each step.

---

## Files

| File | Purpose |
|------|---------|
| `image_grid_maker.py` | The GUI application (run this). |
| `image_grid_core.py`  | Image/scan/grid logic (imported by the app). |
| `test_image_grid_core.py` | Headless tests for the core logic. |
| `requirements.txt` | Python dependencies. |

## Tests

```bash
pip install pillow piexif
python test_image_grid_core.py
```

---

## Tools

### Mass JPEG Resize

This repository also includes a small utility script for batch-resizing JPEG images.

The script recursively scans an input folder, resizes all .jpg and .jpeg files, and saves them into an output folder while preserving the original subfolder structure.

Usage:

python mass_jpeg_resize.py input_folder output_folder scale_percentage jpeg_quality

Example:

python mass_jpeg_resize.py "D:\photos_raw" "D:\photos_resized" 50 90 --workers 16

Arguments:

- input_folder       Source folder containing JPEG files
- output_folder      Destination folder
- scale_percentage   Resize scale percentage, for example 50 means 50%
- jpeg_quality       JPEG quality from 1 to 100
- --workers          Optional number of worker threads

---

## Version

**1.0.5**

- **Reference-image ordering replaces procedural noise.** Load any grayscale image; the app matches photos/sets to it — dark photos to dark areas, and for Colour, warm→bright / cool→dark. Crop or stretch it to the grid; 2-D placement in Photos mode, a 1-D top-to-bottom sweep in Sets mode; Ascending/Descending inverts it.
- **View reference** preview toggle (replaces View noise) shows the image resampled onto the grid.
- All procedural noise controls (Wave / Value-noise / Jitter, frequency / amplitude / phase / seed) were removed.

**1.0.4**

- **Order sets *or* photos:** a new toggle places every photo individually (folders ignored) as well as the existing per-set ordering. In Photos mode every photo is scanned and the Sample control is greyed.
- **Colour source & perceptual colour:** choose **Average** or **Dominant** colour; Colour/Brightness/Similarity ordering now use **CIELAB**.
- **Similarity path:** a new order-by that greedily places each item next to its nearest colour neighbour, for smooth visual flow.
- **View noise (B&W):** a preview toggle that shows the pattern the noise produces as a black-and-white texture.
- **Aspect ratios:** **Select all / Select none** buttons.
- **Mixed mode — use both orientations:** keep both landscapes and portraits from each folder (H-groups first, then V-groups); Mixed mode now also works in Photos order mode (pool by orientation, order group-cells by average colour/brightness/similarity).
- Default colour-sample is now 10; preview defaults are landscape 225,225,225 / portrait 175,175,175.

**1.0.3**

- **Order sets** moved next to the live preview and renamed from "Order folders by". Order sets by name or creation date (ascending/descending); **Randomise** is now its own button.
- New **Scan colours** computes each set's average colour, over **all** photos or an **evenly-spaced sample of N** per set, then lets you order sets by **Colour** (hue) or **Brightness**.
- The live preview now fills each tile with its **set's average colour** (a mosaic of the grid). Scanned colours persist for the session; until you scan, tiles use defaults — landscape 225,225,225 and portrait 175,175,175.
- **Noise arrangement** for colour/brightness ordering: **Wave** (sine, frequency = cycles), **Value noise** (organic clusters) or **Jitter** (loose sort), with adjustable amplitude, phase and a re-rollable seed.
- The order inside each set is unchanged (Date Taken, then file name).

**1.0.2**

- Mixed mode rebuilt as set-based: each folder is one image set (dominant orientation), with selectable base ratio A and width ratio r (1/2, 3/5, 2/3); only ticked aspect-ratio groups are used and the photo-count selection applies per folder first.
- Aspect-ratio groups are split into Landscape and Portrait; Mixed mode is greyed out unless at least one of each is ticked.
- Live preview is now an always-on pane inside the main window (resizable vertical divider) instead of a separate button/window.
- New defaults: output width 3840 px, border 1 px black.

**1.0.1**

- Added folders are expanded into every image-containing sub-folder, each listed
  separately. "Order folders by" (name / creation date / random, asc/desc)
  re-sequences the whole list; picking Random again reshuffles.
- Mixed landscape + portrait mode (two portraits per slot, borders stay aligned).
- Photo selection now has "Use all available photos" (default).
- "Preview structure..." opens a separate window showing the grid's cells,
  borders and portrait splits, with an adjustable preview border width (black, default 1px; scales to any photo count).
- "Fit output exactly to width x aspect ratio" option for a pixel-exact result.
- Robust on huge photo sets: big JPEGs are decoded at reduced scale (much lower memory, so cells no longer drop out), truncated files are tolerated, and the large-image guard is lifted.
- About box with version and repo link.

**1.0.0** — first public release.

- Folder scanning with parallel metadata read
- Aspect-ratio grouping + crop-to-ratio
- Date-aware sorting, first-N / evenly-spaced selection
- Exact-rectangle grid for any target aspect ratio
- Output-width sizing with uniform cells
- JPEG/PNG, optional border, multi-core rendering
- Drag-and-drop, help buttons, log panel, About box

---

## License

Released under t