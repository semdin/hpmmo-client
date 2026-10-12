"""Paint the world-map sheet (assets/ui/world_map.jpg) from the terrain.

1. godot --headless --path client res://tools/ui/dump_heights.tscn -- /tmp/heights.bin
2. python tools/ui/paint_world_map.py /tmp/heights.bin client/assets/terrain/grounds/layout.json out.png
   then save it as client/assets/ui/world_map.jpg (quality 90).

Hillshade + biome tint (meadow, Forbidden Forest, northern moor, mountain rock
and snow), the Black Lake with depth and shoreline, 20 m contours, the roads and
a parchment wash. Place names are drawn live by the game (HudWorldMap).
"""
import sys
import numpy as np, json
from PIL import Image, ImageFilter, ImageDraw
n=1024
H=np.fromfile(sys.argv[1] if len(sys.argv)>1 else '/tmp/heights.bin',dtype=np.float32).reshape(n,n)
H=np.where(H<-50, np.nan, H)
H=np.nan_to_num(H, nan=np.nanmin(H))
L=json.load(open(sys.argv[2] if len(sys.argv)>2 else 'assets/terrain/grounds/layout.json'))
S=2048  # output px
Hb=np.asarray(Image.fromarray(H).resize((S,S),Image.BICUBIC),np.float32)
cell=2048.0/S
# hillshade
gy,gx=np.gradient(Hb,cell)
az=np.deg2rad(315); alt=np.deg2rad(40)
slope=np.pi/2-np.arctan(np.hypot(gx,gy)*1.6)
aspect=np.arctan2(-gx,gy)
hs=np.sin(alt)*np.sin(slope)+np.cos(alt)*np.cos(slope)*np.cos(az-aspect)
hs=np.clip(hs,0,1)
xs=(np.arange(S)+0.5)*cell-1024
X,Z=np.meshgrid(xs,xs)
# base colours
parch=np.array([226,208,166],np.float32)
meadow=np.array([132,146,92],np.float32)
forest=np.array([62,88,58],np.float32)
moor=np.array([170,150,110],np.float32)
rock=np.array([150,140,128],np.float32)
snow=np.array([236,232,224],np.float32)
water=np.array([92,128,150],np.float32)
deep=np.array([58,88,112],np.float32)
col=np.zeros((S,S,3),np.float32)+meadow
def poly_mask(poly):
    im=Image.new('L',(S,S),0); d=ImageDraw.Draw(im)
    d.polygon([((p[0]+1024)/cell,(p[1]+1024)/cell) for p in poly],fill=255)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(18)),np.float32)/255.
reg={r['id']:poly_mask(r['polygon']) for r in L['regions']}
def fbm(scale,seed):
    rr=np.random.default_rng(seed); acc=np.zeros((S,S),np.float32); amp=1.0; tot=0
    for o in range(5):
        k=int(scale*(2**o)); g=rr.random((k,k)).astype(np.float32)
        acc+=amp*np.asarray(Image.fromarray(g).resize((S,S),Image.BICUBIC),np.float32); tot+=amp; amp*=0.5
    return acc/tot
noise=fbm(6,11)
for k in reg:
    reg[k]=np.clip((reg[k]-0.5)*2.2+(noise-0.5)*1.4+0.5,0,1)
col=col*(1-reg['north_moor'][...,None])+moor*reg['north_moor'][...,None]
col=col*(1-reg['forbidden_forest'][...,None])+forest*reg['forbidden_forest'][...,None]
col=col*(0.88+0.24*fbm(10,5))[...,None]
# elevation tint: mountains
e=np.clip((Hb-95)/50,0,1)[...,None]
col=col*(1-e)+rock*e
e2=np.clip((Hb-140)/20,0,1)[...,None]
col=col*(1-e2)+snow*e2
# water
lake=L['lake']; cx,cz=lake['center']; rx,rz=lake['radii']
wmask=(Hb<0.2).astype(np.float32)
wm=np.asarray(Image.fromarray((wmask*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),np.float32)/255.
depth=np.clip(-Hb/12,0,1)[...,None]
wcol=water*(1-depth)+deep*depth
col=col*(1-wm[...,None])+wcol*wm[...,None]
# shade
shade=(0.55+0.6*hs)[...,None]
land=1-wm[...,None]
col=col*(shade*land+(1-land)*(0.92+0.1*hs[...,None]))
# forest stipple: dark dots
rng=np.random.default_rng(3)
ff=reg['forbidden_forest']
dots=(rng.random((S,S))<0.05*ff)&(wm<0.5)
dimg=Image.fromarray((dots*255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))
dm=np.asarray(dimg,np.float32)/255.
col=col*(1-0.35*dm[...,None])
# parchment wash + vignette
col=col*0.88+parch*0.12
r=np.hypot(X,Z)/1024.0
vig=np.clip(1-(r-0.85)*0.9,0.55,1)[...,None]
col=col*vig
# shoreline line
edge=np.asarray(Image.fromarray((wmask*255).astype(np.uint8)).filter(ImageFilter.FIND_EDGES),np.float32)/255.
col=col*(1-0.5*edge[...,None])+np.array([40,60,80])*0.5*edge[...,None]
# contour lines every 20 m
cont=(np.abs((Hb%20.0)-10.0)>9.6)&(wm<0.5)&(Hb>30)
col=col*(1-0.12*cont[...,None])
img=Image.fromarray(np.clip(col,0,255).astype(np.uint8))
d=ImageDraw.Draw(img)
for road in L['roads']:
    pts=[((p[0]+1024)/cell,(p[1]+1024)/cell) for p in road['points']]
    d.line(pts,fill=(118,88,58),width=max(3,int(road['width']*0.9)),joint='curve')
    d.line(pts,fill=(196,170,120),width=max(1,int(road['width']*0.4)),joint='curve')
img=img.filter(ImageFilter.SMOOTH)
img.save(sys.argv[3] if len(sys.argv)>3 else 'world_map.png')
print(img.size, Hb.min(), Hb.max())
