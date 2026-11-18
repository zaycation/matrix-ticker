"""The app's LED-grid icon, drawn with Pillow (tray icon and the installer's .ico)."""
from PIL import Image, ImageDraw

PANEL = (30, 33, 40, 255)
COLORS = [(255, 59, 59), (255, 255, 255), (37, 184, 100), (107, 140, 255), (255, 199, 44)]


def make_image(size=64, running=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 8
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=PANEL)
    cell = size / 6
    for row in range(2, 4):
        for col in range(1, 5):
            c = COLORS[(row * 4 + col) % len(COLORS)]
            x0, y0 = col * cell + cell * 0.15, row * cell + cell * 0.15
            d.ellipse([x0, y0, x0 + cell * 0.7, y0 + cell * 0.7], fill=c)
    if running:  # small green dot in the corner while the ticker runs
        s = size * 0.28
        d.ellipse([size - s - 2, size - s - 2, size - 2, size - 2], fill=(37, 184, 100), outline=PANEL, width=max(1, size // 32))
    return img


def save_ico(path):
    make_image(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
