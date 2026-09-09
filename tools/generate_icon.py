from pathlib import Path
import math
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Rounded midnight tile.
d.rounded_rectangle((44, 44, 980, 980), radius=210, fill="#08111F", outline="#1C314A", width=18)

# Gear teeth + body.
cx = cy = 512
for i in range(12):
    a = math.radians(i * 30)
    x = cx + math.cos(a) * 292
    y = cy + math.sin(a) * 292
    w, h = 92, 150
    box = (x - w/2, y - h/2, x + w/2, y + h/2)
    tooth = Image.new("RGBA", (SIZE, SIZE), (0,0,0,0))
    td = ImageDraw.Draw(tooth)
    td.rounded_rectangle(box, radius=22, fill="#4EA1FF")
    tooth = tooth.rotate(-(i * 30), center=(cx, cy), resample=Image.Resampling.BICUBIC)
    img.alpha_composite(tooth)
d = ImageDraw.Draw(img)
d.ellipse((242, 242, 782, 782), fill="#4EA1FF")
d.ellipse((344, 344, 680, 680), fill="#08111F")

# Download arrow in Factorio-orange for identity/contrast.
orange = "#F39A36"
d.rounded_rectangle((474, 320, 550, 590), radius=30, fill=orange)
d.polygon([(380, 540), (644, 540), (512, 704)], fill=orange)
d.rounded_rectangle((342, 724, 682, 786), radius=28, fill=orange)

png = ASSETS / "icon.png"
ico = ASSETS / "icon.ico"
img.save(png)
img.save(ico, sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(png)
print(ico)
