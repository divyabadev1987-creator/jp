import sys
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
src, out = sys.argv[1], sys.argv[2]
FONT = "/home/user/jp/fonts/Anton-Regular.ttf"
im = Image.open(src).convert("RGB")
im = im.crop((245, 130, 245 + 1550, 130 + 872)).resize((1280, 720), Image.LANCZOS)
im = ImageEnhance.Color(im).enhance(1.25)
im = ImageEnhance.Contrast(im).enhance(1.12)
im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2))
# darken left side for text legibility
shade = Image.new("L", im.size, 0)
sd = ImageDraw.Draw(shade)
for x in range(700):
    sd.line([(x, 0), (x, 720)], fill=int(150 * (1 - x / 700) ** 1.5))
im = Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, shade)
d = ImageDraw.Draw(im)
def text(xy, s, size, fill, stroke=10):
    f = ImageFont.truetype(FONT, size)
    d.text(xy, s, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
text((40, 10), "388 KM/H", 190, (255, 225, 0), 12)
text((46, 225), "ELECTRIC LAMBO", 92, (255, 255, 255), 8)
# 1st badge
d.rounded_rectangle((1060, 30, 1245, 150), radius=22, fill=(255, 40, 150), outline=(0, 0, 0), width=6)
text((1092, 22), "1ST", 104, (255, 255, 255), 6)
im.save(out, quality=95)
