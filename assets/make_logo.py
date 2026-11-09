"""Generates the app logo: a classic red PDF document icon — a rounded-square
sheet with a folded (dog-eared) top-right corner and bold white 'PDF' text —
then exports a multi-resolution .ico for the Windows exe.

Supersampled and downscaled with LANCZOS for crisp anti-aliased edges.
"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
S = 2048          # supersampled working resolution
FINAL = 1024

RED = (226, 10, 10, 255)          # main sheet
FOLD = (176, 0, 0, 255)           # darker underside of the folded corner
WHITE = (255, 255, 255, 255)

FONT_PATH = r"C:\Windows\Fonts\ariblk.ttf"  # Arial Black — heavy blocky letters


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = int(S * 0.055)
    left, top, right, bottom = margin, margin, S - margin, S - margin
    radius = int(S * 0.11)
    fold = int((right - left) * 0.30)  # size of the folded corner

    # --- body silhouette: rounded rect with the top-right corner cut off ---
    body = Image.new("L", (S, S), 0)
    bd = ImageDraw.Draw(body)
    bd.rounded_rectangle([left, top, right, bottom], radius=radius, fill=255)
    # cut the top-right triangle so the corner looks folded away
    bd.polygon([(right - fold, top - 2), (right + 2, top - 2), (right + 2, top + fold)], fill=0)
    # soften the cut's inner corner to match the body radius
    bd.pieslice(
        [right - fold - radius, top, right - fold + radius, top + 2 * radius],
        180, 270, fill=0,
    )

    sheet = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sheet_draw = ImageDraw.Draw(sheet)
    sheet_draw.rectangle([0, 0, S, S], fill=RED)
    img.paste(sheet, (0, 0), body)
    draw = ImageDraw.Draw(img)

    # --- folded corner (dog-ear): darker triangle tucked into the corner ---
    fr = int(radius * 0.55)
    p_top = (right - fold, top)
    p_right = (right, top + fold)
    p_inner = (right - fold, top + fold)
    draw.polygon([p_top, p_right, p_inner], fill=FOLD)
    # round the fold's inner corner a touch
    draw.ellipse([p_inner[0] - fr, p_inner[1] - fr, p_inner[0] + fr, p_inner[1] + fr], fill=FOLD)

    # --- bold white "PDF" ---
    text = "PDF"
    font_size = int(S * 0.285)
    font = ImageFont.truetype(FONT_PATH, font_size)
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    tx = left + ((right - left) - tw) / 2 - tb[0]
    ty = top + ((bottom - top) - th) * 0.56 - tb[1]
    draw.text((tx, ty), text, font=font, fill=WHITE)

    return img.resize((FINAL, FINAL), Image.LANCZOS)


def main():
    final = build()
    png_path = os.path.join(OUT_DIR, "logo.png")
    final.save(png_path)

    ico_path = os.path.join(OUT_DIR, "app.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    final.save(ico_path, sizes=[(s, s) for s in sizes])

    print("saved:", png_path)
    print("saved:", ico_path)


if __name__ == "__main__":
    main()
