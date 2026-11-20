"""Draw OpenNotch's own wallpapers (no third-party art): python3 tools/wallpapers.py OUT_DIR [WIDTH HEIGHT]

ember.png  - a low sun over layered mountain ridges at dusk
mist.png   - pale fog over soft ridges, lots of empty sky for the desktop clock
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vgradient(w, h, stops):
    """stops: [(t, rgb)] top->bottom."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                d.line([(0, y), (w, y)], fill=lerp(c0, c1, (t - t0) / max(1e-6, t1 - t0)))
                break
    return img


def ridge(w, base, amp, seed, rough=0.55, octaves=6):
    """A mountain skyline: y per x, from summed sines with random phases (deterministic per seed)."""
    rnd = random.Random(seed)
    waves = [(rnd.uniform(0, 2 * math.pi), (2 ** i) * rnd.uniform(0.7, 1.3), rough ** i) for i in range(octaves)]
    total = sum(a for _, _, a in waves)
    ys = []
    for x in range(w):
        u = x / w * 2 * math.pi
        v = sum(a * math.sin(u * f + p) for p, f, a in waves) / total
        ys.append(base - amp * v)
    return ys


def draw_ridge(img, ys, color, blur=0):
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon([(0, h)] + [(x, ys[x]) for x in range(w)] + [(w - 1, h)], fill=color)
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def haze(img, y, height, rgb, alpha):
    w, h = img.size
    band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    d.rectangle([0, y, w, y + height], fill=rgb + (alpha,))
    img.alpha_composite(band.filter(ImageFilter.GaussianBlur(height * 0.6)))


def ember(w, h):
    img = vgradient(w, h, [(0, (22, 8, 34)), (0.32, (92, 18, 52)), (0.55, (214, 70, 42)), (0.68, (255, 150, 70)),
                           (1, (60, 12, 20))]).convert("RGBA")
    rnd = random.Random(7)
    stars = ImageDraw.Draw(img)
    for _ in range(260):
        x, y = rnd.randrange(w), rnd.randrange(int(h * 0.35))
        a = rnd.randint(60, 200)
        stars.point((x, y), fill=(255, 235, 220, a))
    # sun with a soft glow and a few horizontal cuts
    cx, cy, r = w * 0.5, h * 0.60, h * 0.17
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - r * 1.9, cy - r * 1.9, cx + r * 1.9, cy + r * 1.9], fill=(255, 120, 60, 90))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(r * 0.6)))
    sun = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sun)
    for i in range(int(2 * r)):
        y = cy - r + i
        half = math.sqrt(max(0, r * r - (y - cy) ** 2))
        sd.line([(cx - half, y), (cx + half, y)], fill=lerp((255, 214, 120), (255, 92, 70), i / (2 * r)) + (255,))
    cut = ImageDraw.Draw(sun)
    for k in range(4):
        y = cy + r * (0.25 + k * 0.18)
        cut.rectangle([cx - r, y, cx + r, y + 2 + k * 1.5], fill=(0, 0, 0, 0))
    img.alpha_composite(sun)
    layers = [((120, 26, 46, 255), h * 0.66, h * 0.10, 1, 3), ((78, 14, 34, 255), h * 0.72, h * 0.11, 2, 2),
              ((44, 8, 24, 255), h * 0.80, h * 0.12, 3, 1), ((18, 4, 12, 255), h * 0.90, h * 0.10, 4, 0)]
    for color, base, amp, seed, blur in layers:
        draw_ridge(img, ridge(w, base, amp, seed), color, blur)
        haze(img, int(base - amp * 0.4), int(h * 0.04), (255, 110, 70), 28)
    return img.convert("RGB")


def mist(w, h):
    img = vgradient(w, h, [(0, (188, 204, 214)), (0.5, (222, 230, 234)), (1, (200, 210, 216))]).convert("RGBA")
    layers = [((150, 168, 180, 140), h * 0.62, h * 0.07, 11, 6), ((120, 140, 154, 180), h * 0.70, h * 0.09, 12, 4),
              ((88, 104, 118, 220), h * 0.80, h * 0.10, 13, 2), ((56, 66, 78, 255), h * 0.92, h * 0.08, 14, 1)]
    for color, base, amp, seed, blur in layers:
        draw_ridge(img, ridge(w, base, amp, seed, rough=0.5), color, blur)
        haze(img, int(base - amp * 0.7), int(h * 0.06), (236, 242, 245), 110)
    return img.convert("RGB")


def main(argv):
    out = argv[1] if len(argv) > 1 else "."
    w, h = (int(argv[2]), int(argv[3])) if len(argv) > 3 else (1920, 1080)
    os.makedirs(out, exist_ok=True)
    for name, fn in (("ember", ember), ("mist", mist)):
        path = os.path.join(out, f"{name}.png")
        fn(w, h).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main(sys.argv)
