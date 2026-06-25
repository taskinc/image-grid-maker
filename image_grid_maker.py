"""
Image Grid Maker
=========================
A desktop GUI that turns thousands of photogrammetry photos into a single
grid image (an exact square/rectangle, no empty cells).

Pipeline:
  1. Pick source folders (drag them in, or use Add folder). Sub-folders optional.
  2. Scan: every image is read in parallel and grouped by aspect ratio.
  3. Tick which aspect ratios to include + one ratio to crop everything to.
  4. Sorted by sub-folder (A-Z), then Date Taken (EXIF), then name.
  5. Choose how many photos and how to pick them (First N / Evenly spaced).
  6. Target output aspect ratio -> closest exact grid.
  7. Output width in px (uniform cells), JPEG/PNG + quality.
  8. Optional border, and CPU usage.

Requires: Python 3.8+, Pillow, tkinterdnd2 (for drag-and-drop).
"""

import os
import time
import threading
import traceback
import multiprocessing
import webbrowser
import random
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox

import image_grid_core as core
from PIL import Image, ImageDraw, ImageTk

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except Exception:  # pragma: no cover
    TkinterDnD = None
    DND_FILES = None

_BaseTk = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk

APP_NAME = "Image Grid Maker"
VERSION = "1.0.2"
AUTHOR = "cagri taskin"
GITHUB_URL = "https://github.com/taskinc/image-grid-maker"

HELP = {
    "folders": ("Add the folders that hold your photos (or drag them in). With "
                "'Expand sub-folders' on, every nested folder that contains images "
                "is listed separately, as if you added each one. 'Order folders by' "
                "re-sequences the whole list by name, folder creation date, or "
                "random (pick Random again to reshuffle); the grid follows this order."),
    "scan": ("Reads every image to get its pixel size, capture date (EXIF) and "
             "aspect ratio. Run this after choosing folders — the results feed "
             "all the options below."),
    "ratios": ("Photos are grouped by shape. Tick the ratios you want to include. "
               "'Crop all included photos to' sets one cell shape; any included "
               "photo of a different shape is centre-cropped to it. The most common "
               "ratio is pre-selected.\n\n"
               "Ratios are split into Landscape and Portrait lists; only ticked "
               "groups are used. Mixed mode needs at least one Landscape AND one "
               "Portrait ratio ticked, otherwise it is greyed out.\n\n"
               "Mixed mode (set-based): each FOLDER is one set, classified by its "
               "dominant orientation among the ticked images (the other orientation "
               "is dropped). Your photo-count selection is applied per folder first. "
               "'Base ratio A' is the landscape ratio (verticals use 1/A); 'r' "
               "(1/2, 3/5, 2/3) is the portrait-to-landscape width ratio. Landscapes "
               "pack in groups of 1/3/2 and portraits in groups of 2/5/3 (equal-"
               "width), filling one perfect rectangle in folder order. Sets with "
               "< 15 usable images are skipped; A must be >= 1/sqrt(r) or the combo "
               "is disabled."),
    "selection": ("'Use all available photos' (default) places every included photo. "
                  "Untick it to cap the count: 'First N' takes them in order, "
                  "'Evenly spaced' samples uniformly across the whole set."),
    "layout": ("Type the aspect ratio you want the finished grid to be (e.g. 16:9). "
               "The app finds the closest exact rows x columns so there are never "
               "any empty cells."),
    "resolution": ("Output width sets the final image width in pixels (default 3840); "
                   "the height follows the aspect ratio and every cell ends at the "
                   "same size, whatever the source resolution. JPEG is smaller (set "
                   "quality); PNG is lossless."),
    "border": ("A frame drawn around and between the cells. Width in pixels "
               "(default 1; 0 = no border) and a colour (default black)."),
    "performance": ("How much of your CPU to use for scanning and rendering. Higher "
                    "is faster but uses more of your machine. 80% is a good default; "
                    "small jobs run single-threaded automatically."),
}


class App(_BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Image Grid Maker")
        try:
            _ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "imagegridmaker.ico")
            if os.path.exists(_ico):
                self.iconbitmap(_ico)
        except Exception:
            pass
        self.geometry("1340x880")
        self.minsize(1080, 640)

        self.PAD = {"padx": 8, "pady": 3}

        # State
        self.folders = []
        self.photos = []
        self.matching = []
        self.ratio_vars = {}
        self.bucket_to_ar = {}
        self.crop_label_to_bucket = {}
        self.border_color = "#000000"
        self._order_seed = 0

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _group(self, parent, title, help_key):
        """A LabelFrame whose title bar carries a '?' help button."""
        lf = ttk.LabelFrame(parent)
        head = ttk.Frame(lf)                     # labelwidget must be a child of lf
        ttk.Label(head, text=title).pack(side="left")
        ttk.Button(head, text="?", width=2,
                   command=lambda: messagebox.showinfo(title, HELP[help_key])
                   ).pack(side="left", padx=4)
        lf.configure(labelwidget=head)
        lf.pack(fill="x", **self.PAD)
        return lf

    def _build_ui(self):
        # App on the left, live preview on the right, with a draggable divider.
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=1)

        # Start with the divider centred (app and preview equal width).
        def _center_sash(event):
            paned.sashpos(0, max(1, event.width // 2))
            paned.unbind("<Configure>", self._sash_cid)
        self._sash_cid = paned.bind("<Configure>", _center_sash)

        # ----- LEFT: app controls -----
        bottom = ttk.Frame(left)
        bottom.pack(side="bottom", fill="both")

        g = ttk.Frame(bottom)
        g.pack(fill="x", padx=10, pady=(6, 2))
        self.generate_btn = ttk.Button(g, text="Generate grid...", command=self.start_generate)
        self.generate_btn.pack(side="left")
        self.progress = ttk.Progressbar(g, mode="determinate", length=240)
        self.progress.pack(side="left", padx=10)
        ttk.Button(g, text="About", command=self.show_about).pack(side="right")

        logf = ttk.LabelFrame(bottom, text="Log")
        logf.pack(fill="both", padx=10, pady=(2, 8))
        self.log_text = tk.Text(logf, height=6, wrap="word", state="disabled")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        canvas = tk.Canvas(left, highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        root = ttk.Frame(canvas, padding=10)
        win = canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _wheel)
        root.bind("<MouseWheel>", _wheel)

        # ----- RIGHT: live structure preview (always on) -----
        ph = ttk.Frame(right); ph.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(ph, text="Live preview (grid structure)").pack(side="left")
        ttk.Label(ph, text="border px:").pack(side="left", padx=(12, 2))
        self._preview_border_var = tk.IntVar(value=1)
        ttk.Spinbox(ph, from_=0, to=40, width=5, textvariable=self._preview_border_var,
                    command=self._render_preview_cv).pack(side="left")
        self._preview_border_var.trace_add("write", lambda *_a: self._render_preview_cv())
        self._preview_cv = tk.Canvas(right, bg="#f7f7f7", highlightthickness=0)
        self._preview_cv.pack(fill="both", expand=True, padx=8, pady=6)
        self._preview_info = ttk.Label(right, text="", anchor="w",
                                       wraplength=420, justify="left")
        self._preview_info.pack(fill="x", padx=8, pady=(0, 8))
        self._preview_cv.bind("<Configure>", lambda _e: self._render_preview_cv())

        # --- 1. Source folders ---------------------------------------
        f1 = self._group(root, "1.  Source folders", "folders")
        top = ttk.Frame(f1); top.pack(fill="x", padx=6, pady=6)
        self.folder_list = tk.Listbox(top, height=3)
        self.folder_list.pack(side="left", fill="both", expand=True)
        b = ttk.Frame(top); b.pack(side="left", fill="y", padx=6)
        ttk.Button(b, text="Add folder...", command=self.add_folder).pack(fill="x", pady=2)
        ttk.Button(b, text="Remove", command=self.remove_folder).pack(fill="x", pady=2)
        ttk.Button(b, text="Clear", command=self.clear_folders).pack(fill="x", pady=2)
        self.expand_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(b, text="Expand sub-folders",
                        variable=self.expand_var).pack(fill="x", pady=2)
        ordr = ttk.Frame(f1); ordr.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Label(ordr, text="Order folders by:").pack(side="left")
        self.order_by_var = tk.StringVar(value="Name")
        ob = ttk.Combobox(ordr, textvariable=self.order_by_var, width=14, state="readonly",
                          values=["Name", "Date created", "Random"])
        ob.pack(side="left", padx=6)
        ob.bind("<<ComboboxSelected>>", lambda _e: self._apply_folder_order())
        self.order_dir_var = tk.StringVar(value="Ascending")
        od = ttk.Combobox(ordr, textvariable=self.order_dir_var, width=12, state="readonly",
                          values=["Ascending", "Descending"])
        od.pack(side="left", padx=6)
        od.bind("<<ComboboxSelected>>", lambda _e: self._apply_folder_order())
        hint = "Tip: drag folders from your file explorer onto this window."
        if TkinterDnD is None:
            hint = "(Install 'tkinterdnd2' to enable drag-and-drop of folders.)"
        ttk.Label(f1, text=hint, foreground="#666").pack(anchor="w", padx=8, pady=(0, 4))

        # --- 2. Scan -------------------------------------------------
        f2 = self._group(root, "2.  Scan & analyse", "scan")
        r2 = ttk.Frame(f2); r2.pack(fill="x", padx=6, pady=6)
        ttk.Button(r2, text="Scan folders", command=self.start_scan).pack(side="left")
        self.scan_label = ttk.Label(r2, text="Not scanned yet.")
        self.scan_label.pack(side="left", padx=8)

        # --- 3. Aspect ratios ----------------------------------------
        f3 = self._group(root, "3.  Aspect ratios", "ratios")
        self.ratio_frame = ttk.Frame(f3)
        self.ratio_frame.pack(fill="x", padx=6, pady=4)
        ttk.Label(self.ratio_frame, text="Scan first.").pack(anchor="w")
        cr = ttk.Frame(f3); cr.pack(fill="x", padx=6, pady=4)
        ttk.Label(cr, text="Crop all included photos to:").pack(side="left")
        self.crop_var = tk.StringVar()
        self.crop_combo = ttk.Combobox(cr, textvariable=self.crop_var, width=16, state="readonly")
        self.crop_combo.pack(side="left", padx=6)
        self.crop_combo.bind("<<ComboboxSelected>>", lambda _e: self.preview_layout())
        mr = ttk.Frame(f3); mr.pack(fill="x", padx=6, pady=(0, 2))
        self.mixed_var = tk.BooleanVar(value=False)
        self.mixed_check = ttk.Checkbutton(
            mr, text="Mixed mode (combine horizontal + vertical folder sets)",
            variable=self.mixed_var, command=self._on_mix_change)
        self.mixed_check.pack(side="left")
        mr2 = ttk.Frame(f3); mr2.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(mr2, text="Base ratio A:").pack(side="left")
        self.mixA_var = tk.StringVar()
        self.mixA_combo = ttk.Combobox(mr2, textvariable=self.mixA_var, width=12)
        self.mixA_combo.pack(side="left", padx=4)
        self.mixA_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_mix_change())
        self.mixA_combo.bind("<KeyRelease>", lambda _e: self._on_mix_change())
        ttk.Label(mr2, text="r:").pack(side="left", padx=(8, 0))
        self.mixR_var = tk.StringVar(value="1/2")
        rc = ttk.Combobox(mr2, textvariable=self.mixR_var, width=6, state="readonly",
                          values=["1/2", "3/5", "2/3"])
        rc.pack(side="left", padx=4)
        rc.bind("<<ComboboxSelected>>", lambda _e: self._on_mix_change())
        self.mix_valid_label = ttk.Label(mr2, text="", foreground="#a00")
        self.mix_valid_label.pack(side="left", padx=8)

        # --- 4. Selection --------------------------------------------
        f4 = self._group(root, "4.  Photo selection", "selection")
        gr = ttk.Frame(f4); gr.pack(fill="x", padx=6, pady=4)
        self.use_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(gr, text="Use all available photos", variable=self.use_all_var,
                        command=self._toggle_use_all).grid(row=0, column=0, columnspan=3,
                                                           sticky="w", pady=2)
        ttk.Label(gr, text="Number of photos to use:").grid(row=1, column=0, sticky="w", pady=4)
        self.count_var = tk.StringVar(value="100")
        self.count_entry = ttk.Entry(gr, textvariable=self.count_var, width=10)
        self.count_entry.grid(row=1, column=1, sticky="w", padx=6)
        self.count_entry.bind("<KeyRelease>", lambda _e: self.preview_layout())
        self.avail_label = ttk.Label(gr, text="")
        self.avail_label.grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(gr, text="Method:").grid(row=2, column=0, sticky="w", pady=4)
        self.method_var = tk.StringVar(value="first")
        ttk.Radiobutton(gr, text="First N", variable=self.method_var,
                        value="first").grid(row=2, column=1, sticky="w", padx=6)
        ttk.Radiobutton(gr, text="Evenly spaced", variable=self.method_var,
                        value="evenly").grid(row=2, column=2, sticky="w", padx=6)

        # --- 5. Layout -----------------------------------------------
        f5 = self._group(root, "5.  Output layout", "layout")
        gr = ttk.Frame(f5); gr.pack(fill="x", padx=6, pady=4)
        ttk.Label(gr, text="Target aspect ratio (W:H):").grid(row=0, column=0, sticky="w", pady=4)
        self.aspect_var = tk.StringVar(value="3:2")
        ac = ttk.Combobox(gr, textvariable=self.aspect_var, width=12,
                          values=["1:1", "3:2", "2:3", "4:3", "16:9", "16:10", "21:9", "A4 1:1.414"])
        ac.grid(row=0, column=1, sticky="w", padx=6)
        ac.bind("<<ComboboxSelected>>", lambda _e: self.preview_layout())
        ac.bind("<KeyRelease>", lambda _e: self.preview_layout())
        self.layout_label = ttk.Label(f5, text="", wraplength=420, justify="left")
        self.layout_label.pack(anchor="w", padx=8, pady=(2, 8))

        # --- 6. Resolution & format ----------------------------------
        f6 = self._group(root, "6.  Resolution & format", "resolution")
        gr = ttk.Frame(f6); gr.pack(fill="x", padx=6, pady=4)
        ttk.Label(gr, text="Output width (px):").grid(row=0, column=0, sticky="w", pady=4)
        self.width_var = tk.StringVar(value="3840")
        we = ttk.Entry(gr, textvariable=self.width_var, width=10)
        we.grid(row=0, column=1, sticky="w", padx=6)
        we.bind("<KeyRelease>", lambda _e: self.preview_layout())
        ttk.Label(gr, text="(height follows the aspect ratio; every cell same size)").grid(
            row=0, column=2, sticky="w", padx=6)
        ttk.Label(gr, text="Format:").grid(row=1, column=0, sticky="w", pady=4)
        self.format_var = tk.StringVar(value="JPEG")
        ttk.Radiobutton(gr, text="JPEG", variable=self.format_var, value="JPEG",
                        command=self._toggle_quality).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Radiobutton(gr, text="PNG", variable=self.format_var, value="PNG",
                        command=self._toggle_quality).grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(gr, text="JPEG quality:").grid(row=2, column=0, sticky="w", pady=4)
        self.quality_var = tk.IntVar(value=90)
        self.quality_scale = ttk.Scale(gr, from_=1, to=100, orient="horizontal",
                                       variable=self.quality_var, length=180,
                                       command=lambda v: self.quality_lbl.config(text=str(int(float(v)))))
        self.quality_scale.grid(row=2, column=1, sticky="w", padx=6)
        self.quality_lbl = ttk.Label(gr, text="90")
        self.quality_lbl.grid(row=2, column=2, sticky="w", padx=6)
        self.fit_exact_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(gr, text="Fit output exactly to width x aspect ratio",
                        variable=self.fit_exact_var,
                        command=self.preview_layout).grid(row=3, column=0, columnspan=3,
                                                          sticky="w", pady=(4, 2))

        # --- 7. Border -----------------------------------------------
        f7 = self._group(root, "7.  Border", "border")
        gr = ttk.Frame(f7); gr.pack(fill="x", padx=6, pady=4)
        ttk.Label(gr, text="Border width (px, 0 = none):").grid(row=0, column=0, sticky="w", pady=4)
        self.border_var = tk.StringVar(value="1")
        be = ttk.Entry(gr, textvariable=self.border_var, width=8)
        be.grid(row=0, column=1, sticky="w", padx=6)
        be.bind("<KeyRelease>", lambda _e: self.preview_layout())
        self.color_btn = ttk.Button(gr, text="Pick colour...", command=self.pick_color)
        self.color_btn.grid(row=0, column=2, padx=6)
        self.color_swatch = tk.Label(gr, text="    ", bg=self.border_color, relief="sunken", width=4)
        self.color_swatch.grid(row=0, column=3, padx=4)

        # --- 8. Performance ------------------------------------------
        f8 = self._group(root, "8.  Performance", "performance")
        gr = ttk.Frame(f8); gr.pack(fill="x", padx=6, pady=4)
        cores = os.cpu_count() or 1
        ttk.Label(gr, text="CPU cores to use (%):").grid(row=0, column=0, sticky="w", pady=4)
        self.cpu_var = tk.StringVar(value="80")
        ce = ttk.Entry(gr, textvariable=self.cpu_var, width=6)
        ce.grid(row=0, column=1, sticky="w", padx=6)
        ce.bind("<KeyRelease>", lambda _e: self._update_cpu_label())
        self.cpu_label = ttk.Label(gr, text="")
        self.cpu_label.grid(row=0, column=2, sticky="w", padx=6)
        self._cores = cores
        self._update_cpu_label()

        self._toggle_quality()
        self._toggle_use_all()
        self._update_mixed_enabled()

        # Drag-and-drop registration.
        if TkinterDnD is not None:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
                self.folder_list.drop_target_register(DND_FILES)
                self.folder_list.dnd_bind("<<Drop>>", self._on_drop)
            except Exception as exc:
                self.log("Drag-and-drop unavailable: %s" % exc)

        self.log("Ready. Add or drag in folders, then Scan.")

    # --------------------------------------------------------------- about
    def show_about(self):
        win = tk.Toplevel(self)
        win.title("About " + APP_NAME)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=20)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=APP_NAME, font=("", 14, "bold")).pack()
        ttk.Label(frm, text="Version " + VERSION).pack(pady=(4, 0))
        ttk.Label(frm, text="by " + AUTHOR).pack(pady=(2, 10))
        link = ttk.Label(frm, text=GITHUB_URL, foreground="#1a73e8", cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda _e: webbrowser.open(GITHUB_URL))
        btns = ttk.Frame(frm)
        btns.pack(pady=(12, 0))
        ttk.Button(btns, text="Open on GitHub",
                   command=lambda: webbrowser.open(GITHUB_URL)).pack(side="left", padx=4)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="left", padx=4)
        win.transient(self)
        win.grab_set()
        self.wait_window(win)

    # --------------------------------------------------------------- log
    def post(self, func):
        self.after(0, func)

    def log(self, msg):
        def _a():
            self.log_text.config(state="normal")
            self.log_text.insert("end", time.strftime("%H:%M:%S  ") + msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.post(_a)

    # --------------------------------------------------------------- helpers
    def _toggle_quality(self):
        self.quality_scale.config(state="normal" if self.format_var.get() == "JPEG" else "disabled")

    def _update_cpu_label(self):
        self.cpu_label.config(text="(%d cores detected -> %d workers)"
                              % (self._cores, self.workers()))

    def parse_aspect(self, text):
        text = text.strip().lower()
        if "1.414" in text or "a4" in text:
            return 1 / 1.414
        if ":" in text:
            w, h = text.split(":")
            return float(w) / float(h)
        return float(text)

    def workers(self):
        try:
            pct = float(self.cpu_var.get())
        except ValueError:
            pct = 80.0
        pct = min(100.0, max(1.0, pct))
        return core.n_workers(pct / 100.0)

    def _int(self, var, default):
        try:
            return int(float(var.get()))
        except ValueError:
            return default

    # --------------------------------------------------------------- folders
    @staticmethod
    def _ctime(path):
        try:
            return os.path.getctime(path)
        except OSError:
            return 0.0

    def _existing_norm(self):
        return {os.path.normcase(os.path.abspath(f)) for f in self.folders}

    def _add_source(self, d):
        """Expand a dropped/added folder into image-containing folders and append new ones."""
        if not d or not os.path.isdir(d):
            return 0
        found = core.dirs_with_images(d, recursive=self.expand_var.get())
        have = self._existing_norm()
        added = 0
        for f in found:
            key = os.path.normcase(os.path.abspath(f))
            if key not in have:
                self.folders.append(f)
                have.add(key)
                added += 1
        return added

    def _populate_folder_list(self):
        self.folder_list.delete(0, "end")
        for f in self.folders:
            self.folder_list.insert("end", f)

    def _apply_folder_order(self):
        by = self._order_by()
        if by == "created":
            self.folders.sort(key=lambda f: self._ctime(f))
        elif by == "random":
            self._order_seed = random.randint(0, 10 ** 9)
            random.Random(self._order_seed).shuffle(self.folders)
        else:
            self.folders.sort(key=lambda f: f.lower())
        if self._order_desc():
            self.folders.reverse()
        self._populate_folder_list()
        if self.photos:
            self.refresh_selection()

    def add_folder(self):
        d = filedialog.askdirectory(title="Select a source folder")
        n = self._add_source(d)
        if n:
            self._apply_folder_order()
            self.log("Added %d folder(s) from: %s" % (n, d))
        elif d:
            self.log("No image folders found in: %s" % d)

    def _on_drop(self, event):
        added = 0
        for item in self.tk.splitlist(event.data):
            d = item if os.path.isdir(item) else (
                os.path.dirname(item) if os.path.isfile(item) else None)
            if d:
                added += self._add_source(d)
        if added:
            self._apply_folder_order()
            self.log("Added %d folder(s) by drag-and-drop." % added)

    def remove_folder(self):
        for i in reversed(list(self.folder_list.curselection())):
            self.folder_list.delete(i)
            del self.folders[i]

    def clear_folders(self):
        self.folders.clear()
        self.folder_list.delete(0, "end")

    def pick_color(self):
        _rgb, hx = colorchooser.askcolor(self.border_color, title="Border colour")
        if hx:
            self.border_color = hx
            self.color_swatch.config(bg=hx)

    # --------------------------------------------------------------- scan
    def start_scan(self):
        if not self.folders:
            messagebox.showwarning("No folders", "Add at least one source folder first.")
            return
        self.generate_btn.config(state="disabled")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            self.log("Scanning %d folder(s) with %d workers..." % (len(self.folders), self.workers()))

            def prog(i, total):
                self.post(lambda: self.progress.config(maximum=total, value=i))

            photos = core.scan_folders(self.folders, False, prog, workers=self.workers())
            if not photos:
                self.log("No images found.")
                self.post(lambda: self.scan_label.config(text="No images found."))
                return

            hist = core.aspect_histogram(photos)
            dom = core.dominant_bucket(photos)
            self.photos = photos
            info = "Found %d images in %d ratio group(s)." % (len(photos), len(hist))
            self.log(info)
            for d in hist:
                self.log("  %s : %d photos" % (d["label"], d["count"]))
            self.post(lambda: self._populate_ratios(hist, dom, info))
        except Exception as exc:
            self.log("Scan failed: %s" % exc)
            msg = "%s\n\n%s" % (exc, traceback.format_exc())
            self.post(lambda: messagebox.showerror("Scan error", msg))
        finally:
            self.post(lambda: self.progress.config(value=0))

    def _populate_ratios(self, hist, dominant, info):
        for child in self.ratio_frame.winfo_children():
            child.destroy()
        self.ratio_vars = {}
        self.bucket_to_ar = {}
        self.crop_label_to_bucket = {}
        labels = []
        dom_label = None
        land = [d for d in hist if d["ar"] >= 1.0]
        port = [d for d in hist if d["ar"] < 1.0]

        def _add_section(title, items):
            if not items:
                return
            ttk.Label(self.ratio_frame, text=title,
                      font=("", 9, "bold")).pack(anchor="w", pady=(4, 0))
            for d in items:
                b = d["bucket"]
                self.bucket_to_ar[b] = d["ar"]
                self.crop_label_to_bucket[d["label"]] = b
                labels.append(d["label"])
                var = tk.BooleanVar(value=(b == dominant))
                self.ratio_vars[b] = var
                ttk.Checkbutton(
                    self.ratio_frame,
                    text="%s   -   %d photos" % (d["label"], d["count"]),
                    variable=var, command=self.refresh_selection).pack(anchor="w", padx=(12, 0))

        _add_section("Landscape", land)
        _add_section("Portrait", port)
        for d in hist:
            if d["bucket"] == dominant:
                dom_label = d["label"]
        self.crop_combo.config(values=labels)
        if dom_label:
            self.crop_var.set(dom_label)
        ab_values = []
        for d in hist:
            ab = d["label"].split(" ")[0]
            if ab not in ab_values:
                ab_values.append(ab)
        self.mixA_combo.config(values=ab_values)
        if dom_label and not self.mixA_var.get():
            self.mixA_var.set(dom_label.split(" ")[0])
        self.scan_label.config(text=info)
        self.generate_btn.config(state="normal")
        self.refresh_selection()

    def refresh_selection(self):
        checked = [b for b, v in self.ratio_vars.items() if v.get()]
        matching = core.filter_by_buckets(self.photos, checked)
        matching = core.order_by_folder_list(matching, self.folders)
        self.matching = matching
        self.avail_label.config(text="(max %d available)" % len(matching))
        try:
            if int(float(self.count_var.get())) > len(matching):
                self.count_var.set(str(len(matching)))
        except ValueError:
            self.count_var.set(str(len(matching)))
        self._update_mixed_enabled()
        self.preview_layout()

    def _update_mixed_enabled(self):
        """Mixed mode needs at least one landscape AND one portrait ratio ticked."""
        if not hasattr(self, "mixed_check"):
            return
        has_land = any(self.bucket_to_ar.get(b, 1.0) >= 1.0
                       for b, v in self.ratio_vars.items() if v.get())
        has_port = any(self.bucket_to_ar.get(b, 1.0) < 1.0
                       for b, v in self.ratio_vars.items() if v.get())
        ok = has_land and has_port
        self.mixed_check.config(state="normal" if ok else "disabled")
        if not ok and self.mixed_var.get():
            self.mixed_var.set(False)
        self._update_mix_validity()

    # --------------------------------------------------------------- layout
    def _order_by(self):
        return {"Name": "name", "Date created": "created",
                "Random": "random"}.get(self.order_by_var.get(), "name")

    def _order_desc(self):
        return self.order_dir_var.get() == "Descending"

    def _toggle_use_all(self):
        self.count_entry.config(state="disabled" if self.use_all_var.get() else "normal")
        self.preview_layout()

    def crop_ar(self):
        b = self.crop_label_to_bucket.get(self.crop_var.get())
        if b is not None and b in self.bucket_to_ar:
            return self.bucket_to_ar[b]
        return None

    def _mix_A(self):
        try:
            return self.parse_aspect(self.mixA_var.get())
        except Exception:
            return None

    def _on_mix_change(self):
        self._update_mix_validity()
        self.preview_layout()

    def _update_mix_validity(self):
        if not hasattr(self, "mix_valid_label"):
            return
        if not self.mixed_var.get():
            self.mix_valid_label.config(text="")
            return
        A = self._mix_A()
        r = self.mixR_var.get()
        if A is None or r not in core.R_VALUES:
            self.mix_valid_label.config(text="enter a valid base ratio A", foreground="#a00")
            return
        if core.mixed_validity(A, r)[0]:
            self.mix_valid_label.config(text="valid", foreground="#080")
        else:
            need = 1.0 / (core.R_VALUES[r] ** 0.5)
            self.mix_valid_label.config(
                text="A must be >= %.3f for r=%s" % (need, r), foreground="#a00")

    def _compute_layout(self):
        if not self.photos:
            return None
        try:
            target_ar = self.parse_aspect(self.aspect_var.get())
        except Exception:
            return None
        if self.mixed_var.get():
            return self._compute_mixed(target_ar)
        if not self.matching:
            return None
        cell_ar = self.crop_ar()
        if cell_ar is None:
            return None
        if self.use_all_var.get():
            count = len(self.matching)
        else:
            count = max(1, min(self._int(self.count_var, 1), len(self.matching)))
        sel = core.select_photos(self.matching, count, self.method_var.get())
        slots = core.make_slots(sel, False)
        if not slots:
            return None
        cols, rows, used = core.best_grid(len(slots), len(slots), cell_ar, target_ar)
        photos = core.count_photos_in_slots(slots[:used])
        return cols, rows, used, target_ar, cell_ar, "normal", photos, slots

    def _compute_mixed(self, target_ar):
        if not self.folders:
            return None
        A = self._mix_A()
        r = self.mixR_var.get()
        if A is None or r not in core.R_VALUES or not core.mixed_validity(A, r)[0]:
            return None
        count = None if self.use_all_var.get() else max(1, self._int(self.count_var, 1))
        method = self.method_var.get()
        by_folder = {}
        for p in self.matching:   # only the ticked aspect-ratio groups
            by_folder.setdefault(os.path.normcase(os.path.abspath(p.folder)), []).append(p)
        sets = []
        for f in self.folders:
            fp = by_folder.get(os.path.normcase(os.path.abspath(f)))
            if fp:
                sets.append(core.select_and_classify(fp, count, method))
        groups = core.build_mixed_groups(sets, r)
        if not groups:
            return None
        cell_ar = core.mixed_cell_ar(r)
        cols, rows, used = core.best_grid(len(groups), len(groups), cell_ar, target_ar)
        photos = core.count_photos_in_groups(groups[:used])
        return cols, rows, used, target_ar, cell_ar, "mixed", photos, groups

    def preview_layout(self):
        """Update the layout summary and the embedded live preview."""
        res = self._compute_layout()
        if not res:
            if hasattr(self, "layout_label"):
                self.layout_label.config(text="")
            self._preview_plan = None
            self._render_preview_cv()
            return
        cols, rows, used, target_ar, cell_ar, mode, photos, cells = res
        bw = max(0, self._int(self.border_var, 0))
        grid_w = max(cols + (cols + 1) * bw, self._int(self.width_var, 3840))
        cw, ch = core.cell_size_from_width(grid_w, cols, cell_ar, bw)
        total_w = cols * cw + (cols + 1) * bw
        total_h = rows * ch + (rows + 1) * bw
        if self.fit_exact_var.get():
            total_w = grid_w
            total_h = max(1, int(round(grid_w / target_ar)))
        out_ar = total_w / total_h
        extra = ("  (mixed: %d groups)" % used) if mode == "mixed" else ""
        self.layout_label.config(
            text=("Grid %dx%d = %d photos%s  |  cell %dx%d px  |  output %dx%d px  "
                  "|  aspect %.3f (target %.3f)" %
                  (cols, rows, photos, extra, cw, ch, total_w, total_h, out_ar, target_ar)))
        self._preview_plan = (cols, rows, cell_ar, cells, used, mode, photos, target_ar)
        self._render_preview_cv()

    def _render_preview_cv(self):
        """Draw the grid structure into one PIL image (fast for any cell count)."""
        cv = getattr(self, "_preview_cv", None)
        if cv is None:
            return
        plan = getattr(self, "_preview_plan", None)
        if plan is None:
            cv.delete("all")
            cv.create_text(max(cv.winfo_width(), 200) / 2, max(cv.winfo_height(), 120) / 2,
                           text="Scan folders and pick options to preview",
                           fill="#888")
            if hasattr(self, "_preview_info"):
                self._preview_info.config(text="")
            return
        cols, rows, cell_ar, cells, used, mode, photos, target_ar = plan
        cv.delete("all")
        W = max(cv.winfo_width(), 320)
        H = max(cv.winfo_height(), 200)
        pad = 12
        try:
            gap = max(0, int(self._preview_border_var.get()))
        except Exception:
            gap = 1
        availw, availh = W - 2 * pad, H - 2 * pad
        # Fit cols x rows (cells of aspect cell_ar) into the available area.
        cw = (availw - (cols + 1) * gap) / cols
        ch = cw / cell_ar
        if rows * ch + (rows + 1) * gap > availh:
            ch = (availh - (rows + 1) * gap) / rows
            cw = ch * cell_ar
        cw = max(1, int(round(cw)))
        ch = max(1, int(round(ch)))
        gw = cols * cw + (cols + 1) * gap
        gh = rows * ch + (rows + 1) * gap

        BLACK = (0, 0, 0)
        land, port = (127, 179, 255), (134, 214, 160)
        img = Image.new("RGB", (max(1, gw), max(1, gh)), BLACK)
        d = ImageDraw.Draw(img)
        n = min(used, cols * rows, len(cells))
        for k in range(n):
            r, c = divmod(k, cols)
            x = gap + c * (cw + gap)
            y = gap + r * (ch + gap)
            cell = cells[k]
            if mode == "mixed":
                t = len(cell[1])
                is_port = (cell[0] == "V")
            else:
                t = 1 if cell[0] == "L" else 2
                is_port = (cell[0] == "P")
            color = port if is_port else land
            if t <= 1 or cw - (t - 1) * gap < 2 * t:
                d.rectangle([x, y, x + cw - 1, y + ch - 1], fill=color)
            else:
                base = max(1, (cw - (t - 1) * gap) // t)
                tx = x
                for i in range(t):
                    tw = base if i < t - 1 else (x + cw - tx)
                    d.rectangle([tx, y, tx + tw - 1, y + ch - 1], fill=color)
                    tx += tw + gap

        # Safety: never exceed the visible canvas.
        if img.width > availw or img.height > availh:
            img.thumbnail((max(1, int(availw)), max(1, int(availh))))
        self._preview_img = ImageTk.PhotoImage(img)   # keep a reference
        cv.create_image(W / 2, H / 2, image=self._preview_img)
        self._preview_info.config(
            text="Grid %dx%d = %d photos%s   |   target aspect %.3f   |   preview border %d px (black)"
            % (cols, rows, photos, " (mixed)" if mode == "mixed" else "", target_ar, gap))

    # --------------------------------------------------------------- generate
    def start_generate(self):
        if not self.photos:
            messagebox.showwarning("Not scanned", "Scan folders first.")
            return
        res = self._compute_layout()
        if not res:
            messagebox.showwarning(
                "Bad input",
                "Nothing to generate. In Mixed mode, check the base ratio A / r are "
                "valid and that at least one folder has >= 15 usable images. "
                "Otherwise check the ratio, photo count and width.")
            return
        cols, rows, used, target_ar, cell_ar, mode, _photos, cells = res
        ext = ".jpg" if self.format_var.get() == "JPEG" else ".png"
        out_path = filedialog.asksaveasfilename(
            title="Save grid as", defaultextension=ext,
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")])
        if not out_path:
            return
        bw = max(0, self._int(self.border_var, 0))
        grid_w = max(cols + (cols + 1) * bw, self._int(self.width_var, 6000))
        fit = bool(self.fit_exact_var.get())
        self.generate_btn.config(state="disabled")
        threading.Thread(target=self._generate_worker,
                         args=(cols, rows, cell_ar, mode, cells[:used], out_path,
                               fit, grid_w, target_ar), daemon=True).start()

    def _generate_worker(self, cols, rows, cell_ar, mode, cells, out_path,
                         fit=False, target_w=0, target_ar=1.5):
        try:
            bw = max(0, self._int(self.border_var, 0))
            grid_w = max(cols + (cols + 1) * bw, self._int(self.width_var, 6000))
            cw, ch = core.cell_size_from_width(grid_w, cols, cell_ar, bw)
            if mode == "mixed":
                photos = core.count_photos_in_groups(cells)
            else:
                photos = core.count_photos_in_slots(cells)

            self.log("Compositing %dx%d grid (%d photos), cell %dx%d px, %d workers..."
                     % (cols, rows, photos, cw, ch, self.workers()))

            def prog(i, total):
                self.post(lambda: self.progress.config(maximum=total, value=i))

            if mode == "mixed":
                img = core.build_mixed_image(cells, cols, rows, cw, ch,
                                             border=bw, border_color=self.border_color,
                                             progress=prog, workers=self.workers())
            else:
                img = core.build_slots_image(cells, cols, rows, cw, ch,
                                             border=bw, border_color=self.border_color,
                                             progress=prog, workers=self.workers())
            if fit:
                img = core.fit_exact(img, target_w, target_ar)
                self.log("Fitted exactly to %dx%d px" % img.size)

            self.log("Saving...")
            core.save_image(img, out_path, self.format_var.get(), self.quality_var.get())
            w_px, h_px = img.size
            self.log("Done: %dx%d px  ->  %s" % (w_px, h_px, out_path))
            done = ("Saved %dx%d grid (%d photos)\n%dx%d px\n\n%s" %
                    (cols, rows, photos, w_px, h_px, out_path))
            self.post(lambda: messagebox.showinfo("Done", done))
        except Exception as exc:
            self.log("Generate failed: %s" % exc)
            msg = "%s\n\n%s" % (exc, traceback.format_exc())
            self.post(lambda: messagebox.showerror("Generate error", msg))
        finally:
            def reset():
                self.progress.config(value=0)
                self.generate_btn.config(state="normal")
            self.post(reset)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    App().mainloop()
