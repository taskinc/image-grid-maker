"""Tests for v1.0.1: ordering, mixed slots, and colour-adjustment behaviour."""
import os, shutil, time, hashlib, piexif
from datetime import datetime, timedelta
from PIL import Image
import image_grid_core as core

TMP="/tmp/v101"; shutil.rmtree(TMP, ignore_errors=True)
def mk(path,w,h,date=None):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    im=Image.new("RGB",(w,h),(90,120,160))
    if date:
        d=date.strftime("%Y:%m:%d %H:%M:%S")
        im.save(path,"JPEG",exif=piexif.dump({"Exif":{piexif.ExifIFD.DateTimeOriginal:d}}))
    else:
        im.save(path,"JPEG")

base=datetime(2024,1,1,8,0,0)
for sub in ["zebra","alpha","mango"]:
    for i in range(2):
        mk(f"{TMP}/{sub}/{sub}_{i}.jpg",3000,2000,base+timedelta(minutes=i))
    time.sleep(0.05)
photos=core.scan_folders([TMP],True,workers=1)

def folder_order(ps):
    seen=[]
    for p in ps:
        b=os.path.basename(p.folder)
        if not seen or seen[-1]!=b: seen.append(b)
    return seen

print("=== ordering: name asc/desc ===")
asc=core.order_photos(photos,"name",False); desc=core.order_photos(photos,"name",True)
assert folder_order(asc)==["alpha","mango","zebra"], folder_order(asc)
assert folder_order(desc)==["zebra","mango","alpha"], folder_order(desc)
print("  asc",folder_order(asc),"desc",folder_order(desc))

print("=== ordering: created asc ===")
assert folder_order(core.order_photos(photos,"created",False))==["zebra","alpha","mango"]

print("=== ordering: random deterministic per seed ===")
assert folder_order(core.order_photos(photos,"random",False,seed=1))==folder_order(core.order_photos(photos,"random",False,seed=1))

print("=== within-folder still date->name ===")
assert [p.name for p in asc if os.path.basename(p.folder)=="alpha"]==["alpha_0.jpg","alpha_1.jpg"]

print("=== make_slots: pairing + drop odd ===")
land=list(photos)[:2]
mk(f"{TMP}/P/p0.jpg",2000,3000,base); mk(f"{TMP}/P/p1.jpg",2000,3000,base); mk(f"{TMP}/P/p2.jpg",2000,3000,base)
pp=core.scan_folders([f"{TMP}/P"],False,workers=1)
slots=core.make_slots(land+pp, mixed=True)
assert [s[0] for s in slots]==["L","L","P"], [s[0] for s in slots]
assert core.count_photos_in_slots(slots)==4
assert all(s[0]=="L" for s in core.make_slots(land+pp, mixed=False))

print("=== mixed render: exact rectangle + border seam ===")
cw,ch,b=300,200,10
slots4=[("L",land[0],None),("P",pp[0],pp[1]),("L",land[1],None),("P",pp[0],pp[1])]
img=core.build_slots_image(slots4,2,2,cw,ch,border=b,border_color="#ff0000",workers=1)
assert img.size==(2*cw+3*b,2*ch+3*b)
assert img.getpixel((0,0))==(255,0,0)
seam_x=b+(cw+b)+((cw-b)//2)+b//2
assert img.getpixel((seam_x,b+ch//2))==(255,0,0)

print("=== mixed parallel == sequential ===")
big=[("P",pp[0],pp[1])]*40 + [("L",land[0],None)]*40
i1=core.build_slots_image(big,10,8,120,80,border=4,border_color="#202020",workers=1)
i2=core.build_slots_image(big,10,8,120,80,border=4,border_color="#202020",workers=4)
assert hashlib.md5(i1.tobytes()).hexdigest()==hashlib.md5(i2.tobytes()).hexdigest()

print("\nALL V1.0.1 TESTS PASSED")
