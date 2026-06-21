"""Headless tests for image_grid_core (run: python test_core.py)."""
import os, shutil, hashlib, colorsys, piexif
from datetime import datetime, timedelta
from PIL import Image
import image_grid_core as core

TMP="/tmp/pg_full"; shutil.rmtree(TMP, ignore_errors=True)
def mk(path,w,h,date=None,hue=0.5):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    r,g,b=[int(c*255) for c in colorsys.hsv_to_rgb(hue,0.55,0.9)]
    im=Image.new("RGB",(w,h),(r,g,b))
    if date:
        d=date.strftime("%Y:%m:%d %H:%M:%S")
        im.save(path,"JPEG",exif=piexif.dump({"Exif":{piexif.ExifIFD.DateTimeOriginal:d}}))
    else:
        im.save(path,"JPEG")

base=datetime(2024,1,1,8,0,0)
# Sub-folder A: dated 3:2, filenames out of chronological order, mixed source res
mk(f"{TMP}/A/a_03.jpg",3000,2000,base+timedelta(days=3))
mk(f"{TMP}/A/a_01.jpg",3000,2000,base+timedelta(days=1))
mk(f"{TMP}/A/a_02.jpg",6000,4000,base+timedelta(days=2))
# Sub-folder B: 3:2 with NO date -> sort by name
mk(f"{TMP}/B/b_zz.jpg",3000,2000)
mk(f"{TMP}/B/b_aa.jpg",3000,2000)
# 3:2 dominant (5 photos). Off-ratio groups below:
for i in range(3): mk(f"{TMP}/A/w_{i}.jpg",1920,1080,base,0.1)   # 16:9 x3
for i in range(2): mk(f"{TMP}/A/sq_{i}.jpg",2000,2000,base,0.6)  # square x2

print("=== scan (parallel == sequential) ===")
seq=core.scan_folders([TMP],True,workers=1)
par=core.scan_folders([TMP],True,workers=4)
assert len(seq)==len(par)==10,(len(seq),len(par))
assert {p.path for p in seq}=={p.path for p in par}

print("=== histogram & dominant ===")
hist=core.aspect_histogram(par); dom=core.dominant_bucket(par)
assert abs(dom-1.5)<0.01
assert hist[0]["count"]==5
print("  groups:",[(d["label"],d["count"]) for d in hist])

print("=== filter + sort ===")
m=core.filter_by_buckets(par,[dom]); m.sort(key=lambda p:p.sort_key())
order=[p.name for p in m]
assert order==["a_01.jpg","a_02.jpg","a_03.jpg","b_aa.jpg","b_zz.jpg"],order
print("  sort:",order)

print("=== selection ===")
assert [p.name for p in core.select_photos(m,3,"first")]==order[:3]
assert len(core.select_photos(m,3,"evenly"))==3

print("=== center crop ===")
assert core._center_crop_to_ratio(Image.new("RGB",(1920,1080)),1.5).size==(1620,1080)
assert core._center_crop_to_ratio(Image.new("RGB",(2000,2000)),1.5).size==(2000,1333)

print("=== include 3:2 + 16:9, crop to 3:2, output width ===")
buckets=[d["bucket"] for d in hist if d["count"] in (5,3)]
mm=core.filter_by_buckets(par,buckets); mm.sort(key=lambda p:p.sort_key())
assert len(mm)==8,len(mm)
cell_ar=1.5
cols,rows,used=core.best_grid(8,len(mm),cell_ar,1.0)
bw=6; grid_w=2400
cw,ch=core.cell_size_from_width(grid_w,cols,cell_ar,bw)
total_w=cols*cw+(cols+1)*bw
assert abs(total_w-grid_w)<=cols+bw+2
assert abs(cw/ch-cell_ar)<0.02

print("=== build: parallel == sequential, exact rectangle ===")
sel=core.select_photos(mm,used,"first")
i1=core.build_grid(sel,cols,rows,cw,ch,cell_ar,border=bw,border_color="#111111",workers=1)
i2=core.build_grid(sel,cols,rows,cw,ch,cell_ar,border=bw,border_color="#111111",workers=4)
assert i1.size==i2.size
assert hashlib.md5(i1.tobytes()).hexdigest()==hashlib.md5(i2.tobytes()).hexdigest()
assert i1.getpixel((0,0))==(17,17,17)
print("  grid %dx%d=%d  out=%s" % (cols,rows,used,i1.size))

print("\nALL TESTS PASSED")
