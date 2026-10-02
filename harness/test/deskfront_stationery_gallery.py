"""Prepare complete native art review; thumbnails zoom independently, never props."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from world.authored_cards import SHAPES, current_dimensions
from world.region_graph import PROP_LABELS, LIBRARY

def prepare(stage):
    rows=[]
    labels={'bookstack':'蓝色装订笔记本','gabion':'彩色索引卡盒','pipe':'六角铅笔','sandbag':'橡皮',
            'crate':'织物笔袋','warehouse':'档案纸盒'}
    def add(key,label,dimensions):
        w,d,h=dimensions
        rows.append(dict(label=label,parts=[[0,0,w,d,key,h]],
                         camera_size=max(w,d,h)*1.7,focus_height=h*.36))
    for key in SHAPES: add(key,labels.get(key,PROP_LABELS[key]),current_dimensions(key))
    for label,size in [('便签捆／低堡垒',(.12,.045,.12)),('立档／堡垒门柱',(.23,.055,.20)),('横放文件夹／堡垒墙',(.55,.045,.20))]:
        add('fort_wall',label,size)
    details={'ruled_sheet':'打孔横线纸','sticky_notes':'三色便利贴','phone':'手机（共享造型）',
             'two_pens':'铅笔（共享造型）','notepad':'夹板便笺','calculator':'计算器（共享造型）',
             'postcard':'风景明信片','usb_drive':'U 盘','coaster':'软木杯垫','cartoon_roach':'工位巡查员彩蛋'}
    for key,label in details.items():rows.append(dict(label=label,detail=key,camera_size=.31,focus_height=.013))
    stage=Path(stage)
    (stage/'stationery-gallery.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    # Audit every actual stored footprint, not just the 21 current card assets.
    shapes={tuple(part[2:]) for cell in LIBRARY['cells'].values() for recipe in cell.values() for part in recipe['covers']}
    shapes.update(tuple(part[2:]) for row in rows for part in row.get('parts',[]))
    source=(Path(__file__).resolve().parents[1]/'src/deskfront/world/stationery.gd').read_text(encoding='utf-8')
    identities=json.loads(re.search(r'const IDENTITIES=(.*)',source)[1])
    for alias,identity in identities.items():
        if any(shape[2]==alias for shape in shapes): continue
        example=next(shape for shape in sorted(shapes) if identities[shape[2]]==identity)
        shapes.add((example[0],example[1],alias,example[3]))
    (stage/'stationery-audit.json').write_text(json.dumps(sorted(shapes)),encoding='utf-8')
    print(json.dumps(dict(gallery=len(rows),physical_variants=len(shapes))))

if __name__=='__main__': prepare(sys.argv[1])
