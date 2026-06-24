"""Tests for the set-based mixed mode."""
import os, shutil, hashlib, math, piexif
from datetime import datetime, timedelta
from PIL import Image
import image_grid_core as core

TMP="/tmp/mix"; shutil.rmtree(TMP, ignore_errors=True)
base=datetime(2024,1,1,8,0,0)
def mk(folder,name,w,h,minute):
    os.makedirs(f"{TMP}/{folder}",exist_ok=True)
    d=(base+timedelta(minutes=minute)).strftime("%Y:%m:%d %H:%M:%S")
    Image.new("RGB",(w,h),(120,120,120)).save(f"{TMP}/{folder}/{name}",
        "JPEG",exif=piexif.dump({"Exif":{piexif.ExifIFD.DateTimeOriginal:d}}))

# Folder H1: 17 landscapes + 3 portraits (dominant horizontal)
for i in range(17): mk("H1",f"l_{i:02d}.jpg",3000,2000,i)
for i in range(3):  mk("H1",f"p_{i:02d}.jpg",2000,3000,100+i)
# Folder V1: 16 portraits + 2 landscapes (dominant vertical)
for i in range(16): mk("V1",f"p_{i:02d}.jpg",2000,3000,i)
for i in range(2):  mk("V1",f"l_{i:02d}.jpg",3000,2000,100+i)
# Folder V2: only 13 portraits -> too few after trim for r=1/2 (12 <15) -> skipped
for i in range(13): mk("V2",f"p_{i:02d}.jpg",2000,3000,i)

def folder_photos(folder):
    return core.scan_folders([f"{TMP}/{folder}"], False, workers=1)

print("=== classify_set ===")
kH,keepH=core.classify_set(folder_photos("H1"))
kV,keepV=core.classify_set(folder_photos("V1"))
assert kH=="H" and len(keepH)==17, (kH,len(keepH))
assert kV=="V" and len(keepV)==16, (kV,len(keepV))
# sorted by date -> landscape names l_00..l_16 in order
assert [p.name for p in keepH][:3]==["l_00.jpg","l_01.jpg","l_02.jpg"]
print("  H1->H(17), V1->V(16) OK")

print("=== validity (balancedCrop>=0) ===")
assert core.mixed_validity(1.5,"1/2")[0] is True
assert core.mixed_validity(1.30,"1/2")[0] is False   # needs >=1.414
assert core.mixed_validity(1.30,"3/5")[0] is True     # needs >=1.291
assert core.mixed_validity(1.20,"2/3")[0] is False    # needs >=1.225
print("  validity thresholds OK")

print("=== cell aspect ===")
for r,exp in [("1/2",1/math.sqrt(.5)),("3/5",3/math.sqrt(.6)),("2/3",2/math.sqrt(2/3))]:
    assert abs(core.mixed_cell_ar(r)-exp)<1e-9
print("  ", {r:round(core.mixed_cell_ar(r),3) for r in core.GROUP_SIZES})

print("=== build_mixed_groups: trailing trim + >=15 skip + folder order ===")
sets=[("H",keepH),("V",keepV),("V",core.classify_set(folder_photos("V2"))[1])]
g12=core.build_mixed_groups(sets,"1/2")   # gh=1,gv=2
# H1: 17 land -> 17 groups; V1: 16//2=8 groups; V2: 12<15 -> skipped
kinds=[g[0] for g in g12]
assert kinds.count("H")==17 and kinds.count("V")==8, (kinds.count("H"),kinds.count("V"))
assert kinds[:17]==["H"]*17 and kinds[17:]==["V"]*8   # folder order preserved
assert core.count_photos_in_groups(g12)==17*1+8*2
# 3/5: H1 17->15 usable ->5 groups(3 each); V1 16->15 usable->3 groups(5 each); V2 skip
g35=core.build_mixed_groups(sets,"3/5")
assert [g[0] for g in g35]==["H"]*5+["V"]*3, [g[0] for g in g35]
assert all(len(g[1])==3 for g in g35[:5]) and all(len(g[1])==5 for g in g35[5:])
print("  1/2:",kinds.count('H'),"H +",kinds.count('V'),"V  |  3/5: 5H + 3V")

print("=== build_mixed_image: exact rectangle + parallel==sequential ===")
cell_ar=core.mixed_cell_ar("1/2")
cols,rows,used=core.best_grid(len(g12),len(g12),cell_ar,1.0)
b=8; grid_w=2000
cw,ch=core.cell_size_from_width(grid_w,cols,cell_ar,b)
i1=core.build_mixed_image(g12[:used],cols,rows,cw,ch,border=b,border_color="#ff0000",workers=1)
i2=core.build_mixed_image(g12[:used],cols,rows,cw,ch,border=b,border_color="#ff0000",workers=4)
assert i1.size==(cols*cw+(cols+1)*b, rows*ch+(rows+1)*b)
assert i1.getpixel((0,0))==(255,0,0)
assert hashlib.md5(i1.tobytes()).hexdigest()==hashlib.md5(i2.tobytes()).hexdigest()
print("  grid %dx%d=%d used  out=%s  identical OK" % (cols,rows,used,i1.size))

print("\nALL MIXED TESTS PASSED")
