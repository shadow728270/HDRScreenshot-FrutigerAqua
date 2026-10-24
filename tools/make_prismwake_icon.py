"""Build the simple Prismwake P + wave Windows application icon (Pillow only)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

out = Path("assets/prismwake.ico")
out.parent.mkdir(parents=True, exist_ok=True)
scale=3
size=256*scale
im=Image.new("RGBA",(size,size),(0,0,0,0))
d=ImageDraw.Draw(im)
b=13*scale
r=64*scale
# Smooth ocean gradient with flat-glass visual simplicity.
d.rounded_rectangle((b,b,size-b,size-b),radius=r,fill=(5,69,111,255),outline=(197,255,249,235),width=5*scale)
for y in range(b+6*scale,size-b-6*scale):
    progress=(y-b)/(size-2*b)
    if progress<0.75:
        alpha=int(38*(1-progress))
        d.line((b+12*scale,y,size-b-12*scale,y),fill=(25,190,203,alpha),width=1)
try:
    font=ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf",155*scale)
except OSError:
    try:font=ImageFont.truetype("DejaVuSans-Bold.ttf",155*scale)
    except OSError:font=ImageFont.load_default()
txt="P"
bbox=d.textbbox((0,0),txt,font=font)
tx=(size-(bbox[2]-bbox[0]))//2-bbox[0]-8*scale
ty=(size-(bbox[3]-bbox[1]))//2-bbox[1]-12*scale
d.text((tx,ty),txt,font=font,fill=(234,255,252,255),stroke_width=1*scale,stroke_fill=(250,255,255,255))
coords=[]
for x in range(39,220):
    t=(x-39)/181
    y=192-11*math.sin(t*math.tau+0.45)-5*math.sin(t*2*math.tau)
    coords.append((x*scale,round(y*scale)))
d.line(coords,fill=(90,249,217,255),width=14*scale,joint="curve")
for x,y in (coords[0],coords[-1]):d.ellipse((x-7*scale,y-7*scale,x+7*scale,y+7*scale),fill=(90,249,217,255))
im=im.resize((256,256),Image.Resampling.LANCZOS)
im.save(out,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"Generated {out} ({out.stat().st_size} bytes)")
